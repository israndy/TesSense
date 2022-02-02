from time import sleep

# To install support module:
# Python3 -m pip install sense_energy
print ("Initating connection to Sense...")
from sense_energy import Senseable
username = 'elon@tesla.com'
password = 'password'
sense = Senseable(wss_timeout=30,api_timeout=30)
sense.authenticate(username, password)

# Python3 -m pip install teslapy
print ("Starting connection to Tesla...")
import teslapy
with teslapy.Tesla('elon@tesla.com') as tesla:
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
        
amps = 5            # Minimum rate charger can go to
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
            amps = vehicles[0].get_vehicle_data()['charge_state']['charge_current_request']
            maxamps = vehicles[0].get_vehicle_data()['charge_state']['charge_current_request_max']
            volts = vehicles[0].get_vehicle_data()['charge_state']['charger_voltage']
        else:
            charging = False
    except :
        charging = False

    if charging :                           # check if need to change rate or stop
        newrate = amps + int( power_diff / volts )
        if newrate > maxamps :
            newrate = maxamps
        if power_diff > 0 :
            print ("Charging at", amps, "amps, with", power_diff, "watts surplus")
            if newrate > amps :
                print ("Increasing charging to", newrate, "amps")
                vehicles[0].command('CHARGING_AMPS', charging_amps = newrate )
                amps = newrate
        else :                                                 # Not enough power
            print ("Charging at", amps, "amps, with", power_diff, "usaage")
            if newrate < 5 :                            # can't charge below 5 amps
                print ("Stopping charge")
                vehicles[0].command('STOP_CHARGE')
                charging = False
            elif newrate < amps :
                print ("Slowing charging to", newrate, "amps")
                vehicles[0].command('CHARGING_AMPS', charging_amps = newrate )
                amps = newrate
    else :                                  # NOT Charging, check if need to start
        print ("Not Charging, Spare power at", power_diff, "watts")
        if power_diff > (5 * volts) :                         # Minimum charge rate
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
                charging = False
            try :
                vehicles[0].command('CHARGING_AMPS', charging_amps=5)
            except :
                print ("Failed to set rate")

    print("Waiting 60 sec...")
    sleep(60) #The fastest the Sense API will update
