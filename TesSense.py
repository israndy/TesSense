"""
 TesSense w/ SenseLink  -Randy Spencer 2022 Version 8
 Python charge monitoring utility for those who own the Sense Energy Monitor
 Uses the stats for Production and Utilization of electricity to control
 your main Tesla's AC charging to use excess production only when charging.
 Simply plug in your car, update your info below, and type> python3 tessense.py

 Added: reporting the Tesla's charging to Sense as if plugged into a TP-Link/Kasa
 Added: geopy checking of location of Tesla to be sure it's charging at home
 Added: sunset and sunrise awareness so it stops the charge after dark
 Added: read & display the watts usage of the other EV charging from the HS-110
 Added: ability to find TP-Link devices on the network and control them.
"""

import datetime
from datetime import timedelta
from time import sleep
import asyncio
import logging, sys

username = 'elon@tesla.com'            # Sense's and TPLink's and Tesla's login
sensepass = 'sense password'           # Sense's password, Tesla will prompt for it's own
TPassword = 'TPLink password'          # TPLink's password
lat, long = 38, -122                   # Location where charging from solar will occur
tz = timedelta(hours=17)               # Take normal TZ offset and subtract it from 24
devicelist = ["Lamp", "TV", "Heater"]  # TPLink Devices to report usage on

#/c Set stdout as logging handler
root_log = logging.getLogger()
root_log.setLevel(logging.WARNING)
handler = logging.StreamHandler(sys.stdout)

# To install support module:
# pip3 install sense_energy
from sense_energy import Senseable

# pip3 install senselink
from senselink import SenseLink
from senselink.plug_instance import PlugInstance
from senselink.data_source import MutableSource

# pip3 install teslapy
import teslapy

# pip3 install geopy
from geopy.geocoders import Nominatim

# pip3 install suntime
from suntime import Sun

# pip3 install tplink-cloud-api
from tplinkcloud import TPLinkDeviceManager, TPLinkDeviceManagerPowerTools


init_time = datetime.datetime.now() - timedelta(hours=4)
print ("Initating connection to Sense...")
sense = Senseable(wss_timeout=30,api_timeout=30)
sense.authenticate(username, sensepass)

def printmsg(msg) :                                        # Timestamped message
    print( " ", datetime.datetime.now().strftime( "%a %I:%M %p" ), msg )
    
def printerror(error, err) :                               # Error message with truncated data
    print(str(err).split("}")[0], "}\n", datetime.datetime.now().strftime( "%a %I:%M %p" ), error)


def UpdateSense() :                                        # Update Sense info via Sense API
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

def PrintUpdate(chargedata, fast) :                        # Display stats at every % change
    print( "\nLevel:",
        chargedata['battery_level'], "%, Limit",
        chargedata['charge_limit_soc'], "%,", volts, "Volts\n Rate:",
        chargedata['charge_amps'], "of a possible",
        chargedata['charge_current_request_max'], "Amps,",
        chargedata['charge_energy_added'], "kWh added, ", end="")
    if not fast : print(
        chargedata['time_to_full_charge'], "Hours remaining\n" )
    else : print(
        chargedata['minutes_to_full_charge'], "Minutes remaining\n" )

def SuperCharging(chargedata) :                       # Loop while DC Fast Charging
    if chargedata['fast_charger_present']:
        printmsg("Supercharging...")
        PrintUpdate(chargedata, 1)
        return(True)
        
def SunNotUp(dr) :                                         # Stop the charging if it's going after sunset
    global init_time                                       # Every 4 hours update the sunrise and sunset times
    if datetime.datetime.now() > init_time + timedelta(hours=4) :
        sun = Sun(dr['latitude'], dr['longitude'])
        sunrise = sun.get_sunrise_time().replace(tzinfo=None) + tz
        sunset = sun.get_sunset_time().replace(tzinfo=None) + tz
        now = datetime.datetime.utcnow() + tz
        if sunrise < sunset : print("🌅 Sunrise:", sunrise, "🌄 Sunset:", sunset)
        else : print("🌄 Sunset:", sunset, "🌅 Sunrise:", sunrise)
        init_time = datetime.datetime.now()
        return(sunset < now < sunrise)         # SunNotUp if sunset is before now and sunrise after

def SendCmd(car, cmd, err) :                               # Start or Stop charging
    try :
        car.command(cmd)
    except teslapy.VehicleError as e : printmsg(e)

def StopCharging(car) :
    print( "Stopping charge" )
    SendCmd(car, 'STOP_CHARGE', "Failed to stop")

def StartCharging(car, minrate) :
    try :
        cardata = car.get_vehicle_data()       # Collect new data from Tesla
    except teslapy.HTTPError as e:
        printerror("Tesla failed to update, please wait a minute...", e)
        return
    chargedata = cardata['charge_state']
    if chargedata['charging_state'] != "Charging" :
        SendCmd(car, 'START_CHARGE', "Won't start charging")
        newrate = min(int(power_diff / volts), chargedata['charge_current_request_max'])
        if -5 < newrate < minrate : newrate = 0            # Deadzone where charger is on at zero amps
        print("Starting charge at", newrate, "Amps")
        SetAmps(car, newrate, "Won't start charging 2")    # Set the Amps twice for values under 5 amps
        if newrate < 5 : SetAmps(car, newrate, "Won't start charging 3")
        
def SetAmps(car, newrate, err) :                           # Increase or decrease charging rate
    try :
        car.command('CHARGING_AMPS', charging_amps = newrate)
    except teslapy.VehicleError as e : printerror("V: "+err, e)
    except teslapy.HTTPError as e: printerror("H: "+err, e)

def ChangeCharging(car, newrate, msg) :
    print( msg, "charging to", newrate, "amps" )
    SetAmps(car, newrate, "Failed to change")
    if newrate < 5 : SetAmps(car, newrate, "Failed to change 2") # if under 5 amps you need to set it twice

def Wake(car) :
    printmsg("Waking...")
    try : car.sync_wake_up()
    except teslapy.VehicleError as e : printerror("Won't wake up", e)
    except teslapy.HTTPError as e: printerror("Failed to wake", e)
     
    
async def TesSense() :
    global mutable_plug
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
                try :
                    cardata = vehicles[0].get_vehicle_data() # Collect new data from Tesla
                except teslapy.HTTPError as e:
                    printerror("Tesla failed to update, please wait a minute...", e)
                    await asyncio.sleep(60)                # Error: Return to top of order
                    continue
                #print(round(cardata['drive_state']['latitude'], 3),round(cardata['drive_state']['longitude'], 3)) # Location of car at present
                chargedata = cardata['charge_state']
                    
                if SuperCharging(chargedata) :             # Display any Supercharging or DCFC data
                    await asyncio.sleep(120)               # Loop while Supercharging back to top
                    continue
                    
                elif round(cardata['drive_state']['latitude'], 3) != lat and round(cardata['drive_state']['longitude'], 3) != long :
                    printmsg('Away from home, wait two minutes') # Prevent remote charging issues with app
                    await asyncio.sleep(120)
                    continue
                    
                else :                                     # Calculate new rate of charge
                    rate = chargedata['charge_current_request']
                    newrate = min(rate + int(power_diff/volts), chargedata['charge_current_request_max'])
                    if -5 < newrate < minrate : newrate = 0 # Deadzone where charger is on at zero amps
                                        
                if chargedata['charging_state'] == "Charging" : # Charging, update status
                    if chargedata['battery_level'] < chargedata['charge_limit_soc'] :
                        fullORunplugged = 0                # Mark it as NOT full and AS plugged-in

                    if SunNotUp(cardata['drive_state']) :  # Stop charging, the sun went down
                        StopCharging(vehicles[0])
                        printmsg("Nighttime")
                        await asyncio.sleep(120)
#                        await asyncio.sleep(sunrise - datetime.datetime.now())
                        continue

                    if  level != chargedata['battery_level'] or limit != chargedata['charge_limit_soc'] :
                        level, limit = chargedata['battery_level'], chargedata['charge_limit_soc']
                        PrintUpdate(chargedata, 0)         # Display charging info every % change
                                                           
                    if rate == 0 :                         # Display what we have been doing:
                        if power_diff > minrate * volts :
                            print( "Not charging, free power", power_diff, "watts")
                        else :
                            print( "Not charging, have", power_diff, "watts, need", minrate * volts)
                            
                    elif power_diff > 1 :                  # Enough free power
                        print( "Charging at", rate, "amps, with", power_diff, "watts surplus" )
                    elif power_diff < -1 :                 # Not enough free power
                        print( "Charging at", rate, "amps, with", power_diff, "watts usage" )
                    else :                                 # power_diff = -1, 0 or 1, so don't say "watts"
                        print( "Charging at", rate, "amps" )
                                                           
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
                            StartCharging(vehicles[0], minrate)
                            mutable_plug.data_source.power = rate * volts
                            rate = newrate
                    else :
                        print( "Not Charging, usage is at", power_diff, "watts" )

            else :                                         # Sleeping, check if need to wake and charge
                if power_diff > ( minrate * volts ) and not fullORunplugged :
                    Wake(vehicles[0])                      # Also an initial daytime wake() to get status
                    rate = newrate = 0                     # Reset rate as things will have changed
                    continue
                else : print("Sleeping, free power is", power_diff, "watts" ) # Just not enough to charge

            printmsg(" Wait two minutes...")               # Message after every complete loop
            await asyncio.sleep(120)                       # Fastest the Sense API will update is 30 sec.
            
           
async def CheckTPLink() :                       # Based on github.com/piekstra/tplinkcloud-service
    global output

    def printmsg(msg) :
        print("=" * len(msg))
        print(msg)
        print("-" * len(msg))
    
    printmsg("Looking for TPLink smartplugs")
    device_manager = TPLinkDeviceManager(username, TPassword)
    power_manager  = TPLinkDeviceManagerPowerTools(device_manager)
    devices = await power_manager.get_emeter_devices()
    if not devices : printmsg("No TPLink (KASA) E-Meter devices found")
    else :
        print("="*75)
        print("Found "+str(len(devices))+" TP-Link E-Meter devices:")
        for i, device in enumerate(devices, 1) :
            print('{:25}'.format(device.device_info.alias), end='' if i % 3 else '\n')
        if i % 3: print()
        print("-"*75)
        while(True) :
            output = ''
            for nameddevice in devicelist :
                try:
                    unit = await device_manager.find_device(nameddevice)
                except:
                    printmsg("Cannot find TPLink device")
                    await asyncio.sleep(60)
                    continue
                if unit.device_info.status :                    # Check if unit is online
                    try:
                        device = await power_manager.get_devices_power_usage_realtime(nameddevice)
                    except:
                        printmsg("Cannot find TPLink device status")
                        await asyncio.sleep(60)
                        continue
                    usage = device[0]
                    if hasattr(usage.data, 'voltage_mv') :
                        if usage.data.voltage_mv > 1000 :                   # If old model data
                            watts = usage.data.power_mw/1000
                            if watts > 5 :
                                if output != '' : output = output + "\n"
                                output = output + nameddevice + " = " + str(round(usage.data.voltage_mv/1000, 2)) + " volts, "+ str(round(usage.data.power_mw/1000,2)) +    " watts, "+ str(round(usage.data.current_ma/1000,2)) +  " amps, "+ str(round(usage.data.total_wh/1000,2)) +    " 7-day kW/hs"
                        else :                                              # If new model data
                            watts = usage.data.power_mw
                            if watts > 5 :
                                if output != '' : output = output + "\n"
                                output = output + nameddevice + " = " + str(round(usage.data.voltage_mv,2)) +       " volts, "+ str(round(usage.data.power_mw,2)) +         " watts, "+ str(round(usage.data.current_ma, 2)) +      " amps, "+ str(round(usage.data.total_wh,2)) +         " 7-day kW/hs"
                        if watts > 5 and mutable_plug.data_source.power == 0 and power_diff < -(watts/3) :
                            printmsg("Powering off: "+ nameddevice + " " + str(power_diff) + " less than " + str(-(round(watts/3,1))))
                            await unit.power_off()
                        if 5 < watts < 1200 and nameddevice == 'Mitsubishi MiEV' :
                            printmsg("Powering off iMiev is full")
                            await unit.power_off()
            if output != '' :
                print("=" * 72)
                print(output)
                print("-" * 72)
            await asyncio.sleep(120)


async def main():                                          # Much thanks to cbpowell for this SenseLink code:
    global mutable_plug
    # Create controller, with NO config
    controller =  SenseLink(None)
    
    # Create a PlugInstance, setting at least the name for Sense and MAC
    mutable_plug = PlugInstance("mutable", alias="Tesla", mac="53:75:31:f8:3a:8c")
    # Create and assign a Mutable Data Source to that plug
    mutable_data_source = MutableSource("mutable", None)
    mutable_plug.data_source = mutable_data_source
    
    # Add that plug to the controller
    controller.add_instances({mutable_plug.identifier: mutable_plug})

    # Pass plug to TesSense, where TesSense can update it
    tp_task  = CheckTPLink()
    tes_task = TesSense()

    # Get SenseLink tasks to add these
    tasks = controller.tasks
    tasks.add(tes_task)
    tasks.add(tp_task)
    tasks.add(controller.server_start())

    logging.info("Starting SenseLink controller")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Interrupt received, stopping SenseLink")
