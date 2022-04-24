import requests

BASE = "http://127.0.0.1:5000/"

data = [{'name': 'John', 'views': 12000, 'likes': 10},
        {'name': 'Jack', 'views': 14000, 'likes': 14},
        {'name': 'Anna', 'views': 18000, 'likes': 41},
        {'name': 'Brad', 'views': 2000, 'likes': 5}]

for i in range(len(data)):
    response = requests.put(BASE + "video/" + str(i), data[i])
    print(response.json())

input()

response = requests.get(BASE + "video/2", {})
print(response.json())

input()

response = requests.patch(BASE + "video/2", {'views' : 15500})
print(response.json())