from flask import Flask, request, render_template, jsonify
import threading, time, socket
from gpiozero import PWMLED, MCP3008
from time import sleep
from pythonosc.udp_client import SimpleUDPClient

pot1 = MCP3008(0)
pot2 = MCP3008(1)
pot3 = MCP3008(2)
pot4 = MCP3008(3)
osc_ip = "127.0.0.1"   # change if your OSC target is on another device
osc_port = 5005        # Carlas OSC UDP port (make sure this matches Carla)
client = SimpleUDPClient(osc_ip, osc_port)

lastVal1=0
lastVal2=0
lastVal3=0
lastVal4=0

while True:
	print("Pot 1: " + str(int(pot1.value*100)))
	print("Pot 2: " + str(int(pot2.value*100)))
	print("Pot 3: " + str(int(pot3.value*100)))
	print("Pot 4: " + str(int(pot4.value*100)))
	print()
	
	if (abs(int(pot1.value*100)-lastVal1)>2):
		client.send_message("/Carla/00/set_parameter_value", [0, pot1.value*48-24])
	if (abs(int(pot2.value*100)-lastVal2)>2):
		client.send_message("/Carla/0/set_parameter_value", [1, pot2.value*48-24])
	if (abs(int(pot3.value*100)-lastVal3)>2):
		client.send_message("/Carla/0/set_parameter_value", [2, pot3.value*48-24])
	if (abs(int(pot4.value*100)-lastVal4)>2):
		client.send_message("/Carla/0/set_parameter_value", [3, pot4.value*48-24])
	lastVal1=int(pot1.value*100)
	lastVal2=int(pot2.value*100)
	lastVal3=int(pot3.value*100)
	lastVal4=int(pot4.value*100)	
	sleep(0.5)
