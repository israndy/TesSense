#import re
#from datetime import datetime
#from datetime import date
#from datetime import time
from time import sleep

print ("Initating connection to Sense...")
from sense_energy import Senseable
username = 'israndy@yahoo.com'
password = 'getbe5-buvqiw-bugPut'
sense = Senseable(wss_timeout=30,api_timeout=30)
sense.authenticate(username, password)

print ("Starting connection to Tesla...")
import teslapy
with teslapy.Tesla('israndy@yahoo.com') as tesla:
    vehicles = tesla.vehicle_list()
    try:
        print(vehicles[0].get_vehicle_data()['display_name'], " ", vehicles[0].get_vehicle_data()['charge_state']['charging_state'])
        if vehicles[0].get_vehicle_data()['charge_state']['charging_state'] == "Charging":
            charging = True
        else:
            charging = False
    except:
        print("Vehicle may be sleeping\n")
        charging = False

rate = 5            # Minimum rate charger can go to
threshold = 600     # Minimum watts needed to start charging
volts = 120         # Minimum volts in those watts

while (True):
    sense.update_realtime()
    active_power = str(sense.active_power).split('.')[0]
    active_solar_power = str(sense.active_solar_power).split('.')[0]
    asp = int(active_solar_power)
    ap = int(active_power)
    power_diff = asp-ap

    try :
        if vehicles[0].get_vehicle_data()['charge_state']['charging_state'] == "Charging":
            charging = True
            maxamps = vehicles[0].get_vehicle_data()['charge_state']['charge_current_request_max']
            rate = vehicles[0].get_vehicle_data()['charge_state']['charge_current_request']
            volts = vehicles[0].get_vehicle_data()['charge_state']['charger_voltage']
            threshold = rate * volts
        else:
            charging = False
    except :
        charging = False

    newrate = rate + int( power_diff / volts )

    if charging :                           # check if need to change rate or stop
        if (power_diff > 0) :
            print ("Charging at", rate, "amps, with", power_diff, "watts surplus")
            if newrate > maxamps :
                newrate = maxamps
            if newrate < 5 :                                # minimum charge rate
                    newrate = 5
            if newrate > rate :
                print ("Increasing charging to", newrate, "amps")
                vehicles[0].command('CHARGING_AMPS', charging_amps = newrate )
                rate = newrate
            elif rate < newrate :
                print ("Slowing charging to", newrate, "amps")
                vehicles[0].command('CHARGING_AMPS', charging_amps = newrate )
                rate = newrate
        else :                                                 # Not enough power
            print ("Charging at", rate, "amps, with", power_diff, "watts to spare")
            if ((newrate - rate ) * volts ) < power_diff :
                print ("Stopping charge")
                vehicles[0].command('STOP_CHARGE')
                charging = False

    else :                                # NOT Charging, check if need to start
        print ("Not Charging, Spare power at", power_diff)
        if power_diff > (5 * volts) :                           # Minimum charge rate
            try :
                print ("Starting charge")
                vehicles[0].sync_wake_up()
            except :
                print ("Failed to wake")
            sleep(10)
            try :
                vehicles[0].command('START_CHARGE')
                charging = True
            except :
                print ("failed to start charging")
            try :
                vehicles[0].command('CHARGING_AMPS', charging_amps=5)
            except :
                print ("Failed to set rate")
                charging = False

    print("Waiting 60 sec...")
    sleep(60) #The fastest the Sense API will update
