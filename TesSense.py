import datetime, sys, logging
from time import sleep
from suntime import Sun
import geopy.geocoders  # 1.14.0 or higher required
from geopy.geocoders import Nominatim
from geopy.exc import *

# To install support module:
# Python3 -m pip install sense_energy
from sense_energy import Senseable

# Python3 -m pip install senselink
import asyncio
from senselink import SenseLink
from senselink.plug_instance import PlugInstance
from senselink.data_source import MutableSource

# Python3 -m pip install teslapy
import teslapy

"""
 TesSense w/ SenseLink  -Randy Spencer 2022 Version 7
 Python charge monitoring utility for those who own the Sense Energy Monitor
 Uses the stats for Production and Utilization of electricity to control
 your main Tesla's AC charging to use excess production only when charging.
 Simply plug in your car, update your info below, and type> python3 tessense.py

 Added: reporting the Tesla's charging to Sense as if plugged into a TP-Link/Kasa
 Added: geopy checking of location of Tesla to be sure it's charging at home
 Added: sunset and sunrise awareness so it stops the charge after dark
 Add: read & display the watts usage of the other EV charging from the HS-110
 Add: ability to find TP-Link devices on the network and control them.
"""

username = 'elon@tesla.com'         # Sense's and Tesla's login
password = 'password'               # Sense's password, Tesla will prompt for it's own
homeaddress = ''

print ("Initating connection to Sense...")
sense = Senseable(wss_timeout=30,api_timeout=30)
sense.authenticate(username, password)

#/c Set stdout as logging handler
root_log = logging.getLogger()
root_log.setLevel(logging.WARNING)
handler = logging.StreamHandler(sys.stdout)

def printmsg(msg) :                                        # Timestamped message
    print( " ", datetime.datetime.now().strftime( "%a %I:%M %p" ), msg )
    
def printerror(error, err) :                               # Error message with truncated data
    print(str(err).split("}")[0], "}\n", datetime.datetime.now().strftime( "%a %I:%M %p" ), error)


def UpdateSense() :                                        # Update Sense info
    global power_diff, volts
    try :
        sense.update_realtime()
    except :
        printmsg("Sense Timeout")
        return(True)
    else :
        volts = int(sense.active_voltage[0] + sense.active_voltage[1])
        asp = int(sense.active_solar_power)
        ap = int(sense.active_power)
        power_diff = asp-ap                                # Watts being sent back to the grid

def UpdateTesla(car) :                                     # Grab the latest charge info from the Tesla
    global cardata
    global chargedata
    try :
        cardata = car.get_vehicle_data()
    except teslapy.HTTPError as e:
        printerror("Tesla failed to update, please wait a minute...", e)
        return(True)
    chargedata = cardata['charge_state']

def PrintUpdate(fast) :                                    # Display stats at every % change
    print( "\nLevel:",
        chargedata['battery_level'], "%, Limit",
        chargedata['charge_limit_soc'], "%,",
        chargedata['charge_energy_added'], "kWh added, ", end="")
    if not fast : print(
        volts, "Volts\n Rate is",
        chargedata['charge_amps'], "of a possible",
        chargedata['charge_current_request_max'], "Amps,",
        chargedata['time_to_full_charge'], "Hours remaining\n" )
    else : print(
        chargedata['charge_rate'], "Charge Rate, ",
        chargedata['minutes_to_full_charge'], "Minutes remaining\n" )

def CheckSuperCharging() :                                 # Loop while DC Fast Charging
    if chargedata['fast_charger_present']:
        printmsg("Supercharging...")
        PrintUpdate(1)
        return(True)
        
def Locate(vehicle, dr) :                                  # First check if the car is at home
    coords = '%s, %s' % (dr['latitude'], dr['longitude'])
    try:
        osm = Nominatim(user_agent='TeslaPy', proxies=vehicle.tesla.proxies)
        location = osm.reverse(coords).address
    except (GeocoderTimedOut, GeocoderUnavailable) as e:
        printerror("Geocoder error", e)
    else:
        logging.info(location)
        return(location)
        
def SunNotUp(vehicle, drive_state) :                       # Stop the charging if it's going after sunset
    sun = Sun(drive_state['latitude'], drive_state['longitude'])
    sunrise = sun.get_local_sunrise_time().replace(tzinfo=None)
    sunset = sun.get_local_sunset_time().replace(tzinfo=None)
    now = datetime.datetime.now()
    if sunrise < now < sunset : return(True)

def SendCmd(car, cmd, err) :                               # Start or Stop charging
    try :
        car.command(cmd)
    except teslapy.VehicleError as e : printerror("V: "+err, e)
    except teslapy.HTTPError as e: printerror("H: "+err, e)

def SetAmps(car, newrate, err) :                           # Increase or decrease charging rate
    try :
        car.command('CHARGING_AMPS', charging_amps = newrate)
    except teslapy.VehicleError as e : printerror("V: "+err, e)
    except teslapy.HTTPError as e: printerror("H: "+err, e)

def ChangeCharging(car, newrate, msg) :
    print( msg, "charging to", newrate, "amps" )
    SetAmps(car, newrate, "Failed to change")
    if newrate < 5 : SetAmps(car, newrate, "Failed to change 2")

def StopCharging(car) :
    print( "Stopping charge" )
    SendCmd(car, 'STOP_CHARGE', "Failed to stop")

def StartCharging(car, newrate) :
    if chargedata['charging_state'] != "Charging" :
        print( "Starting charge at", newrate, "Amps")
        SendCmd(car, 'START_CHARGE', "Won't start charging")
        SetAmps(car, newrate, "Won't start charging 2")        # Set the Amps twice for values under 5 amps
        if newrate < 5 : SetAmps(car, newrate, "Won't start charging 3")
        
def Wake(car) :
    print("Waking...")
    try : car.sync_wake_up()
    except teslapy.VehicleError as e : printerror("Won't wake up", e)
    except teslapy.HTTPError as e: printerror("Failed to wake", e)

async def run_tessense(mutable_plug):
    rate = newrate = level = limit = fullORunplugged = 0
    minrate = 3                                            # Minimum rate you want to set the charger to

    retry = teslapy.Retry(total=3, status_forcelist=(500, 502, 503, 504))
    with teslapy.Tesla(username, retry=retry, timeout=20) as tesla:
        vehicles = tesla.vehicle_list()
        print("Starting connection to", vehicles[0].get_vehicle_summary()['display_name']+"...\n")
        
        while (True):
            if UpdateSense() :                             # Collect new data from Energy Monitor
                await asyncio.sleep(20)                    # Error: Return to top of order
                continue
                
            if vehicles[0].available() :                   # Check if car is online
                if UpdateTesla(vehicles[0]) :              # Collect new data from Tesla
                    await asyncio.sleep(60)                # Error: Return to top of order
                    continue
                elif CheckSuperCharging() :                # Display any Supercharging or DCFC data
                    await asyncio.sleep(120)               # Loop while Supercharging back to top
                    continue
                elif Locate(vehicles[0], cardata['drive_state']) != homeaddress :
                    printmsg('Away from home, wait 4 minutes') # Prevent remote charging issues with app
                    await asyncio.sleep(240)
                    continue
                else :                                     # Calculate new rate of charge
                    rate = chargedata['charge_current_request']
                    maxrate = chargedata['charge_current_request_max']
                    newrate = min( rate + int( power_diff / volts ), maxrate )
                    if -5 < newrate < minrate : newrate = 0 # Deadzone where charger is on at zero amps
                                        
                if chargedata['charging_state'] == "Charging" : # Charging, update status
                    if chargedata['battery_level'] < chargedata['charge_limit_soc'] :
                        fullORunplugged = 0                # Mark it as plugged in and not full
                    if SunNotUp(vehicles[0], cardata['drive_state']) :
                        StopCharging(vehicles[0])              # Stop charging, the sun went down
                        printmsg("Nighttime")
                        await asyncio.sleep(120)
                        continue
                    if  level != chargedata['battery_level'] or limit != chargedata['charge_limit_soc'] :
                        level, limit = chargedata['battery_level'], chargedata['charge_limit_soc']
                        PrintUpdate(0)                     # Display charging info every % change
                                                           # Display where we have been:
                    if rate == 0 :
                        if power_diff > minrate * volts :
                            print( "Not charging, free power", power_diff, "watts")
                        else :
                            print( "Not charging, have", power_diff, "watts, need", minrate * volts)
                    elif power_diff > 1 :                    # Enough free power to maybe increase
                        print( "Charging at", rate, "amps, with", power_diff, "watts surplus" )
                    elif power_diff < -1 :                 # Not enough free power to continue
                        print( "Charging at", rate, "amps, with", power_diff, "watts usage" )
                    else : print( "Charging at", rate, "amps" ) # power_diff = -1, 0 or 1, so don't say "watts"
                                                           
                    if newrate < 0 :                       # Stop charging as there's no free power
                        StopCharging(vehicles[0])
                    elif newrate > rate :                  # Charge faster with any surplus
                        ChangeCharging(vehicles[0], newrate, "Increasing")
                    elif newrate < rate :                  # Charge slower due to less availablity
                        ChangeCharging(vehicles[0], newrate, "Slowing")
                    rate = newrate
                    mutable_plug.data_source.power = rate * volts # Update Sense with current info (Ha!)
                    
                else :                                     # Not charging, check if need to start
                    mutable_plug.data_source.power = 0     # Let Sense know we are not charging
                    if power_diff > ( minrate * volts ) :  # Minimum free watts to start charge
                        if chargedata['charging_state'] == "Disconnected":
                            SetAmps(vehicles[0], newrate, "Error during rate setting")
                            print("Please plug in, power at", power_diff, "watts" )
                            fullORunplugged = 2
                        elif chargedata['battery_level'] >= chargedata['charge_limit_soc'] :
                            print("Full Battery, power at", power_diff, "watts" )
                            fullORunplugged = 1
                        else :
                            StartCharging(vehicles[0], newrate)
                            rate = newrate
                    else :
                        print( "Not Charging, usage is at", power_diff, "watts" )

            else :                                         # Sleeping, check if need to wake and charge
                if power_diff > ( minrate * volts ) and not fullORunplugged :
                    Wake(vehicles[0])                      # Also an initial daytime wake() to get status
                    rate = newrate = 0   # Reset rate as things will have changed
                    continue
                else : print("Sleeping, free power is", power_diff, "watts" ) # Just not enough to charge

            printmsg(" Wait two minutes...")               # Message after every complete loop
            await asyncio.sleep(120)                       # Fastest the Sense API will update is 30 sec.
            

async def main():                                          # Much thanks to cbpowell for this SenseLink code:
    global mutable_plug
    # Create controller, with NO config
    controller =  SenseLink(None)
    
    # Create a PlugInstance, setting at least the identifier and MAC
    mutable_plug = PlugInstance("mutable", alias="Tesla", mac="53:75:31:f8:3a:8c")
    # Create and assign a Mutable Data Source to that plug
    mutable_data_source = MutableSource("mutable", None)
    mutable_plug.data_source = mutable_data_source
    
    # Add that plug to the controller
    controller.add_instances({mutable_plug.identifier: mutable_plug})

    # Pass plug to TesSense, where TesSense can update it
    tes_task = run_tessense(mutable_plug)

    # Get SenseLink tasks to add these
    tasks = controller.tasks
    tasks.add(tes_task)
    tasks.add(controller.server_start())

    logging.info("Starting SenseLink controller")
    await asyncio.gather(*tasks)



if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Interrupt received, stopping SenseLink")
