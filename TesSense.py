username = 'elon@tesla.com'         # Sense's and Tesla's login
password = 'password'               # Sense's password, Tesla will prompt for it's

#
# TesSense  -Randy Spencer 2022
# Python charge monitoring utility for those who own the Sense Energy Monitor
# Uses the stats for Production and Utilization of electricity to control
# your main Tesla's AC charging to use excess production only when charging.
# Simply plug in your car, update your info above, and type> python3 teslasense.py
#
# Add: averaging the last 4 minutes to remove powering off due to spikes/clouds
# Add: reporting the Tesla's charging to Sense as if plugged into a TP-Link/Kasa
# Add: ability to find TP-Link devices on the network and control them.

import datetime
from time import sleep
from os.path import exists # Needed to open a Supercharger log file

# To install support module:
# Python3 -m pip install sense_energy
print ("Initating connection to Sense...")
from sense_energy import Senseable
sense = Senseable(wss_timeout=30,api_timeout=30)
sense.authenticate(username, password)

# Python3 -m pip install teslapy
print ("Starting connection to Tesla...")
import teslapy
with teslapy.Tesla( username ) as tesla:
    vehicles = tesla.vehicle_list()
    car = vehicles[0].get_vehicle_summary()
    print(car['display_name'], "is", car['state'], "\n")
    try : charge=vehicles[0].get_vehicle_data()['charge_state']['battery_level']
    except teslapy.HTTPError as e:
        print( "Failed to get battery status\n", str(e).split("}")[0], "}" )
        charging = False
    else : print(charge, "%\n")

rate = minrate = 2            # Minimum rate you want to set the charger to
volts = 120                   # Minimum volts until detected by the charger

while (True):
    try :
        sense.update_realtime()
        asp = int(sense.active_solar_power)
        ap = int(sense.active_power)
        power_diff = asp-ap
    except :
        print( "Sense Timeout" )
        sleep(10)
        continue # back to the top of the order

    try : car = vehicles[0].get_vehicle_summary()
    except teslapy.HTTPError as e:
        print( "Failed to get summary", str(e).split("}")[0], "}" )
        sleep(30)
        continue
    
    if car['in_service'] : exit( car['display_name'], "is driving" )
    if car['state'] == 'online' :
        try :
            cardata=vehicles[0].get_vehicle_data()
        except teslapy.HTTPError as e:
            print( datetime.datetime.now().strftime( "%I:%M %p" ), "Tesla failed to update, please wait a minute...\n", str(e).split("}")[0], "}" )
            sleep(60)
            continue # back to the top of the order
            
        if cardata['charge_state']['charging_state'] == "Disconnected":
            exit("Please plug the vehicle in")
        if cardata['charge_state']['charging_state'] == "Charging":
            charging = True
            rate = cardata['charge_state']['charge_current_request']
            maxrate = cardata['charge_state']['charge_current_request_max']
            volts = cardata['charge_state']['charger_voltage']
        else:
            charging = False
        
    if charging :                           # check if need to change rate or stop
        newrate = min( rate + int( power_diff / volts ), maxrate )
        if power_diff > 1 :
            print( "Charging at", rate, "amps, with", power_diff, "watts surplus" )
            if newrate > rate :
                print( "Increasing charging to", newrate, "amps" )
                try :
                    vehicles[0].command( 'CHARGING_AMPS', charging_amps = newrate )
                    if newrate < 5 :
                        vehicles[0].command( 'CHARGING_AMPS', charging_amps = newrate )
                    rate = newrate
                except teslapy.HTTPError as e:
                    print( "failed up\n", str(e).split("}")[0], "}" )
        elif power_diff < -1 :                                    # Not enough power
            print( "Charging at", rate, "amps, with", power_diff, "watts usage" )
            if newrate < minrate :                       # can't charge below minrate
                print( "Stopping charge" )
                try :
                    vehicles[0].command( 'STOP_CHARGE' )
                except teslapy.HTTPError as e: print( "failed to stop\n", str(e).split("}")[0] )
                charging = False
            elif newrate < rate :
                print( "Slowing charging to", newrate, "amps" )
                try :
                    vehicles[0].command( 'CHARGING_AMPS', charging_amps = newrate )
                    if newrate < 5 :
                        vehicles[0].command( 'CHARGING_AMPS', charging_amps = newrate )
                    rate = newrate
                except teslapy.HTTPError as e:
                    print( "failed down\n", str(e).split("}")[0], "}" )

        else : print( "Charging at", rate, "amps" ) # -1, or 1 watt or 0 watts diff
                
    else :                                  # NOT Charging, check if time to start
        print( "Not Charging, Spare power at", power_diff, "watts" )
        if power_diff > ( minrate * volts ) :                    # Minimum charge watts
            print( "Starting charge" )
            try : vehicles[0].sync_wake_up()
            except teslapy.HTTPError as e :
                print( "Failed to wake\n", str(e).split("}")[0], "}" )
                sleep( 10 )
            print( "On", car['display_name'] )
            if vehicles[0].get_vehicle_summary()['state'] == 'online' :
                try :
                    if vehicles[0].get_vehicle_data()['charge_state']['charging_state'] != "Charging" :
                        vehicles[0].command( 'START_CHARGE' )
                        vehicles[0].command( 'CHARGING_AMPS', charging_amps=minrate )
                        vehicles[0].command( 'CHARGING_AMPS', charging_amps=minrate )
                        charging = True
                except teslapy.HTTPError as e :
                    print( "failed to start charging\n", str(e).split("}")[0], "}" )
                    charging = False

    if charge and charge != cardata['charge_state']['battery_level'] :
        charge = cardata['charge_state']['battery_level']
        print("\n", charge, "%\n")
    print( datetime.datetime.now().strftime( "%I:%M %p" ), " Wait a minute..." )
    sleep( 60 ) #The fastest the Sense API will update
