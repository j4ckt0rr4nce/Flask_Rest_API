from django.db import models
from django.utils import timezone
from django.core.validators import RegexValidator, MaxValueValidator
from django.utils.translation import ugettext_lazy as _

from wagtail.contrib.settings.models import BaseSetting, register_setting
from wagtail.admin.edit_handlers import PageChooserPanel, FieldPanel
from wagtail.images.edit_handlers import ImageChooserPanel

from datetime import timedelta

from ..home.constants import COUNTRY_CHOICES, COUNTRY_CHOICE_CZ, JOB_CHOICES, STATUS_CHOICES, PROGRESS_CHOICE_CART, \
    PROGRESS_CHOICE_PLACED, PROGRESS_CHOICE_SEND, PROGRESS_CHOICE_PAID
from ...libraries.models import CustomUser
from ...libraries import emails


# Create your models here.


@register_setting(icon="doc-full-inverse")
class ShopSettings(BaseSetting):
    gdpr_page = models.ForeignKey(
        'wagtailcore.Page',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+'
    )
    shop_terms_page = models.ForeignKey(
        'wagtailcore.Page',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='+++'
    )
    header_img = models.ForeignKey('wagtailimages.Image', on_delete=models.PROTECT, null=True, blank=True,
                                   related_name="basket_img")
    orders_email = models.EmailField('Email pro zprávy z eshopu', null=True)

    panels = [
        PageChooserPanel('gdpr_page'),
        PageChooserPanel('shop_terms_page'),
        ImageChooserPanel('header_img'),
        FieldPanel('orders_email')
    ]

    class Meta:
        verbose_name = _('Eshop nastavení')


class OrderQueryset(models.QuerySet):

    # ---------- Getters ----------

    def get_current_for_user(self, user):
        try:  # fixme -- tady je mozna bug, protoze je tu filtr a latest a asi se nevraci ten exception
            return self.filter(user=user, progress__in=[PROGRESS_CHOICE_CART]).latest('updated_at')
        except Order.DoesNotExist:
            pass

    def get_from_request(self, request, create=True):

        if not hasattr(request, '_order') or request._order is None:
            order_id = request.session.get('order_id', None)

            if request.user.is_authenticated:
                order_obj = self.get_current_for_user(request.user)

                if order_obj is not None:
                    request.session['order_id'] = order_obj.id

                # zjistim zda nemam order_obj i ze session a pokud jo, tak zkusim prehodit order_items
                try:
                    order_obj_from_session = Order.objects.get(id=order_id, progress__in=[PROGRESS_CHOICE_CART])
                except Order.DoesNotExist:
                    order_obj_from_session = None

                if order_obj_from_session is not None and order_obj is not None and \
                        order_obj.id != order_obj_from_session.id:
                    order_obj.course = order_obj_from_session.course
                    order_obj_from_session.delete()  # smazu ten ze session pac uz ho nepotrebuju

                # pokud nemam order_obj z db, tak nastavim ten ze session
                if order_obj is None and order_obj_from_session is not None:
                    order_obj = order_obj_from_session

            else:
                try:
                    order_obj = Order.objects.get(id=order_id, progress__in=[PROGRESS_CHOICE_CART])
                except Order.DoesNotExist:
                    order_obj = None

            if order_obj is None and create:
                order_obj = Order.objects.create()
                request.session['order_id'] = order_obj.id

            if order_obj and not order_obj.date_placed and request.user.is_authenticated and (order_obj.user is None):
                order_obj.user = request.user
                order_obj.save()

            request._order = order_obj

        return request._order


class BaseProductMixin(models.Model):
    product_name = models.CharField(max_length=254, null=True, blank=True, verbose_name=_('Název produktu'))
    num_in_stock = models.PositiveIntegerField(verbose_name="Počet kusů k prodeji", null=True, blank=True)
    short_desc = models.CharField(verbose_name=_('Krátký popis'), max_length=254, null=True, blank=True)
    product_code = models.PositiveIntegerField(verbose_name="Kód produktu", null=False, blank=False,
                                               validators=[MaxValueValidator(99)])
    image = models.ForeignKey(
        'wagtailimages.Image', null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+', verbose_name=_('Obrázek')
    )
    # prices
    price_text = models.CharField(verbose_name="Náhradní text za cenu", null=True, blank=True, max_length=255)
    price = models.PositiveIntegerField(verbose_name="Cena", null=True, blank=True)
    graduate_price = models.PositiveIntegerField(verbose_name="Cena pro absolventa", null=True, blank=True)
    student_price = models.PositiveIntegerField(verbose_name="Cena pro studenta", null=True, blank=True)
    vat = models.PositiveSmallIntegerField(verbose_name="Výše DPH v %", null=True, blank=True)

    reg_price = models.PositiveIntegerField(verbose_name="Cena pro absolventy a studenty", null=True, blank=True)

    class Meta:
        abstract = True

    @property
    def price_vat_inc(self):
        return int(self.price * ((self.vat / 100) + 1))

    @property
    def reg_price_vat_inc(self):
        if self.reg_price:
            return int(self.reg_price * ((self.vat / 100) + 1))

    @property
    def in_stock(self):
        return self.num_in_stock > 0

    def get_product_name(self):
        if self.product_name:
            return self.product_name
        return "Produkt: {}".format(self.title)


class Order(models.Model):
    class Meta:
        verbose_name = "Objednávka"
        verbose_name_plural = "Objednávky"
        ordering = ("-date_placed", "id")

    course = models.ForeignKey('courses.CoursePage', on_delete=models.SET_NULL, blank=True, null=True,
                               verbose_name="Kurz", related_name="order_course")
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, blank=True, null=True, related_name="orders",
                             verbose_name="Uživatel")
    registered = models.BooleanField(verbose_name="použít studentskou cenu", blank=True, default=False)
    updated_at = models.DateTimeField('Upravena', auto_now=True)
    price = models.PositiveIntegerField("Cena s DPH", null=True, blank=True)
    progress = models.PositiveSmallIntegerField("Stav", choices=STATUS_CHOICES, default=PROGRESS_CHOICE_CART)
    date_placed = models.DateTimeField("Zadána", null=True, blank=True)
    date_paid = models.DateTimeField("Zaplacena", null=True, blank=True)
    date_sent = models.DateTimeField("Vyřízena", null=True, blank=True)

    phone_regex = RegexValidator(regex=r'^\+?1?\d{9,15}$',
                                 message="Telefonní číslo musí mít formát: '+777123456'.")
    # shipping info
    job = models.PositiveSmallIntegerField("Zaměstnavatel/Student", choices=JOB_CHOICES, null=True, blank=True)
    organization = models.CharField("Název organizace", max_length=254, null=True, blank=True)
    employee_office = models.CharField("Název příslušného úřadu práce", max_length=254, null=True, blank=True)
    # ADRESSES
    same_billing_as_shipping = models.BooleanField("Registrační adresa je shodná s fakturační", default=False)
    # billing info
    bill_company = models.CharField("Firma", max_length=80, null=True, blank=True)
    bill_reg_number = models.CharField("IČO", max_length=8, null=True, blank=True)
    bill_vat_number = models.CharField("DIČ", max_length=20, null=True, blank=True)
    bill_street = models.CharField("Ulice a číslo popisné", max_length=254, null=True, blank=True)
    bill_city = models.CharField("Město", max_length=254, null=True, blank=True)
    bill_zip = models.DecimalField("PSČ", max_digits=5, decimal_places=0, blank=True, null=True)
    bill_email = models.EmailField("Email zaměstnavatele", null=True, blank=True)
    bill_phone = models.CharField("Telefon zaměstnavatele", max_length=20, validators=[phone_regex], null=True,
                                  blank=True)
    variable_symbol = models.CharField("variabilní symbol", max_length=16, null=True, blank=True)

    # others
    agree = models.BooleanField("Souhlas s obchodními podmínkami", null=True, blank=True)
    gdpr = models.BooleanField("Souhlas se zpracováním osobních údajů", null=True, blank=True)
    note = models.TextField("Poznámka", null=True, blank=True)

    objects = OrderQueryset.as_manager()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._progress = self.progress

    def get_participants_count(self) -> int:
        return self.participants.count()

    @property
    def order_price(self):
        if self.progress == PROGRESS_CHOICE_CART:
            total = 0
            if self.course:
                for participant in self.participants.all():
                    total += participant.get_course_price()
            return total
        else:
            return self.price

    # TODO FIX ME
    def course_price(self):
        # if self.student_id and self.course.student_price:
        #     return self.course.student_price
        # elif self.graduate_id and self.course.graduate_price:
        #     return self.course.graduate_price
        if self.registered:
            return self.course.reg_price
        else:
            return self.course.price

    @property
    def deadline_for_payment(self):
        date_start = self.course.date_start
        deadline = self.date_placed + timedelta(days=14)
        if date_start:
            if deadline.date() > date_start:
                return date_start
        return deadline.date()

    def has_credentials(self):
        if self.same_billing_as_shipping:
            if not self.has_multiple_participants():
                participant = self.participants.first()
                return participant.first_name and participant.last_name and participant.birth_date \
                       and participant.email and participant.phone and participant.street
        else:
            return False

    def has_participant(self):
        return True if self.participants.all() else False

    def has_multiple_participants(self):
        return True if self.participants.count() > 1 else False

    def items_in_stock(self):
        return self.course.in_stock

    def was_placed(self):
        return self.progress == PROGRESS_CHOICE_PLACED and self._progress != PROGRESS_CHOICE_PLACED

    def handle_placed(self):
        if not self.date_placed:
            participants = self.participants.all()
            number_of_participants = participants.count()
            self.course.num_in_stock -= number_of_participants
            self.course.number_of_order += number_of_participants
            if self.course.num_in_stock == 0:
                self.course.state = None
            self.course.save()
            self.date_placed = timezone.now()
            if self.same_billing_as_shipping:
                date = self.course.date_start.strftime("%d%m%y") if self.course.date_start else \
                    str(self.course.id).zfill(6)

                self.variable_symbol = "{:02d}{}{:02d}".format(self.course.product_code,
                                                               date,
                                                               self.course.number_of_order)
            from wagtail.core.models import Site
            from home.models import ContactSettings
            shop_settings = ShopSettings.for_site(Site.objects.get(site_name__icontains="institut"))
            contact_settings = ContactSettings.for_site(Site.objects.get(site_name__icontains="institut"))
            receiver_emails = []
            if self.same_billing_as_shipping:
                receiver_emails.append(self.participants.first().email)
            if self.bill_email:
                receiver_emails.append(self.bill_email)
                for participant in self.participants.all():
                    receiver_emails.append(participant.email)
            if receiver_emails:
                emails.send_html_email(emails.EMAIL_ORDER_PLACED, receiver_emails,
                                       email_from=shop_settings.orders_email,
                                       context={"order": self, "site": shop_settings.site,
                                                "variable_symbol": self.variable_symbol,
                                                "bank_account": contact_settings.bank_account})

            emails.send_html_email(emails.EMAIL_ORDER_PLACED_NOTIFICATION, shop_settings.orders_email,
                                   email_from=shop_settings.orders_email,
                                   context={"order": self, "site": shop_settings.site})

    def handle_sent(self):
        if not self.date_sent:
            self.date_sent = timezone.now()
            shop_settings = ShopSettings.objects.first()
            receiver_emails = []
            if self.same_billing_as_shipping:
                receiver_emails.append(self.participants.first().email)
            if self.bill_email:
                receiver_emails.append(self.bill_email)
                for participant in self.participants.all():
                    receiver_emails.append(participant.email)
            if receiver_emails:
                emails.send_html_email(emails.EMAIL_ORDER_SENT, receiver_emails,
                                       email_from=shop_settings.orders_email, context={"order": self,
                                                                                       "site": shop_settings.site})

    def was_sent(self):
        return self.progress == PROGRESS_CHOICE_SEND and self._progress != PROGRESS_CHOICE_SEND

    def handle_paid(self):
        if not self.date_paid:
            self.date_paid = timezone.now()
            shop_settings = ShopSettings.objects.first()
            receiver_emails = []
            if self.same_billing_as_shipping:
                receiver_emails.append(self.participants.first().email)
            if self.bill_email:
                receiver_emails.append(self.bill_email)
                for participant in self.participants.all():
                    receiver_emails.append(participant.email)
            if receiver_emails:
                emails.send_html_email(emails.EMAIL_ORDER_PAID, receiver_emails,
                                       email_from=shop_settings.orders_email, context={"order": self,
                                                                                       "site": shop_settings.site})

    def was_paid(self):
        return self.progress == PROGRESS_CHOICE_PAID and self._progress != PROGRESS_CHOICE_PAID

    def save(self, **kwargs):
        if self.was_placed():
            self.handle_placed()

        if self.was_sent():
            self.handle_sent()

        if self.was_paid():
            self.handle_paid()

        return super().save(**kwargs)


class Participant(models.Model):
    # ORDER
    order = models.ForeignKey('shop.Order', on_delete=models.CASCADE, blank=True, null=True,
                              verbose_name="Objednávka", related_name="participants")

    # MANDATORY FIELDS
    degree_before = models.CharField("Titul před", max_length=30, null=True, blank=True)
    degree_after = models.CharField("Titul za", max_length=30, null=True, blank=True)
    first_name = models.CharField("Jméno", max_length=60, null=True)
    last_name = models.CharField("Příjmení", max_length=60, null=True)
    student_id = models.CharField("ID studenta", max_length=60, null=True, blank=True)
    graduate_id = models.CharField("ID absolventa", max_length=60, null=True, blank=True)
    birth_date = models.DateField("Datum narození", null=True)
    email = models.EmailField("Email účastníka kurzu", null=True)
    phone_regex = RegexValidator(regex=r'^\+?1?\d{9,15}$',
                                 message="Telefonní číslo musí mít formát: '+777123456'.")
    phone = models.CharField("Telefon účastníka kurzu", max_length=20, validators=[phone_regex], null=True)
    is_clerk = models.BooleanField("Jsem uředníkem?", default=False)

    # ADDRESS (only for qualifications courses )
    street = models.CharField("Ulice a číslo popisné", max_length=254, null=True, blank=True)
    city = models.CharField("Město", max_length=254, null=True, blank=True)
    zip = models.DecimalField("PSČ", max_digits=5, decimal_places=0, null=True, blank=True)
    birth_place = models.CharField("Místo narození", max_length=254, null=True)
    country = models.PositiveSmallIntegerField("Kód země", choices=COUNTRY_CHOICES, default=COUNTRY_CHOICE_CZ,
                                               null=True, blank=True)

    def __str__(self):
        return '{} {}'.format(self.first_name, self.last_name)

    def get_course_price(self):
        if self.order.course:
            if self.student_id:
                return self.order.course.student_price
            elif self.graduate_id:
                return self.order.course.graduate_price
            else:
                return self.order.course.price
        return None

    class Meta:
        verbose_name = "Účastník"
        verbose_name_plural = "Účastníci"
