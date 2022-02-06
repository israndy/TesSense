username = 'elon@tesla.com'         # Sense and Tesla login
password = 'password'               # Sense password, Tesla will prompt for it

#
# TesSense
# Python charge monitoring utility for those who own the Sense Energy Monitor
# Uses the stats for Production and Utilization of electricity to control
# your main Tesla's AC charging to use excess production only when charging.
# Simply plug in your car, update your info above, and type> python3 teslasense.py
#

import datetime
from time import sleep

# To install support module:
# Python3 -m pip install sense_energy
print ("Initating connection to Sense...")
from sense_energy import Senseable
sense = Senseable(wss_timeout=30,api_timeout=30)
sense.authenticate(username, password)

# Python3 -m pip install teslapy
print ("Starting connection to Tesla...")
import teslapy
with teslapy.Tesla(username) as tesla:
    vehicles = tesla.vehicle_list()
    car = vehicles[0].get_vehicle_summary()
    print(car['display_name'], "is", car['state'], "\n")
    if car['state'] != 'online' : charging = False
    
amps = 5            # Minimum rate charger can go to
volts = 120         # Minimum volts

while (True):
    try :
        sense.update_realtime()
        asp = int(sense.active_solar_power)
        ap = int(sense.active_power)
        power_diff = asp-ap
    except :
        print("Sense Timeout")
        continue

    car = vehicles[0].get_vehicle_summary()
    if car['in_service'] : exit(car['display_name'], "is driving")
    if car['state'] == 'online' :
        try :
            cardata=vehicles[0].get_vehicle_data()
            if cardata['charge_state']['charging_state'] == "Disconnected":
                exit("Please plug the vehicle in")
            if cardata['charge_state']['charging_state'] == "Charging":
                charging = True
                amps = cardata['charge_state']['charge_current_request']
                maxamps = cardata['charge_state']['charge_current_request_max']
                volts = cardata['charge_state']['charger_voltage']
            else:
                charging = False
        except teslapy.HTTPError as e:
            print("Vehicle sleeping?\n", e)
            charging = False
        
    if charging :                           # check if need to change rate or stop
        newrate = min(amps + int( power_diff / volts ), maxamps)
        if power_diff > 1 :
            print ("Charging at", amps, "amps, with", power_diff, "watts surplus")
            if newrate > amps :
                print ("Increasing charging to", newrate, "amps")
                try :
                    vehicles[0].command('CHARGING_AMPS', charging_amps = newrate )
                except teslapy.HTTPError as e:
                    print("failed up\n", e)
                amps = newrate
        elif power_diff < -1 :                                    # Not enough power
            print ("Charging at", amps, "amps, with", power_diff, "watts usage")
            if newrate < 5 :                            # can't charge below 5 amps
                print ("Stopping charge")
                try :
                    vehicles[0].command('STOP_CHARGE')
                except teslapy.HTTPError as e:
                    print("failed to stop\n", e)
                charging = False
            elif newrate < amps :
                print ("Slowing charging to", newrate, "amps")
                try :
                    vehicles[0].command('CHARGING_AMPS', charging_amps = newrate )
                except teslapy.HTTPError as e:
                    print("failed down\n", e)
                amps = newrate
        else : print ("Charging at", amps, "amps") # -1, or 1 watt or 0 watts diff
                
    else :                                  # NOT Charging, check if time to start
        print ("Not Charging, Spare power at", power_diff, "watts")
        if power_diff > (5 * volts) :                         # Minimum charge rate
            try :
                print ("Starting charge")
                vehicles[0].sync_wake_up()
            except teslapy.HTTPError as e :
                print ("Failed to wake\n", e)
            sleep(10)
            print("On", cardata['display_name'])
            try :
                if vehicles[0].get_vehicle_data()['charge_state']['charging_state'] != "Charging" :
                    vehicles[0].command('START_CHARGE')
                    vehicles[0].command('CHARGING_AMPS', charging_amps=4)
                    vehicles[0].command('CHARGING_AMPS', charging_amps=4)
                    charging = True
            except teslapy.HTTPError as e :
                print ("failed to start charging\n", e)
                charging = False

    print(datetime.datetime.now().strftime("%I:%M %p"), " Wait a minute...")
    sleep(60) #The fastest the Sense API will update
