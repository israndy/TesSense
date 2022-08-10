"""
 TesSense w/ SenseLink  -Randy Spencer 2022 Version 9.5
 Python charge monitoring utility for those who own the Sense Energy Monitor
 Uses the stats for Production and Utilization of electricity to control
 your main Tesla's AC charging to charge only with excess production.
 Simply plug in your car, update your info below, and type> python3 tessense.py

 Added: reporting the Tesla's charging to Sense as if plugged into a TP-Link/Kasa
 Added: checking of location of Tesla to be sure it's charging at home
 Added: read & display the watts usage of the other EV charging from the HS-110
 Added: ability to find TP-Link devices on the network and control them
 Added: tracks cabin temp and local chargers, vents the car if it gets too hot
"""

#username = 'elon@tesla.com'             # Sense's and TPLink's and Tesla's login
#sensepass = 'sense password'            # Sense's password, Tesla will prompt for it's own
#TPassword = 'TPLink password'           # TPLink's password
#lat, lon  = 38, -122                    # Location where charging will occur (shown at startup)
#controllist = ["Lamp", "TV", "Heater"]  # TPLink Devices to control (also shown at startup)

import datetime, asyncio
import logging, sys, json
#/c Set stdout as logging handler
root_log = logging.getLogger()
root_log.setLevel(logging.WARNING) # WARNING or INFO or DEBUG
handler = logging.StreamHandler(sys.stdout)

# To install support module:
# pip3 install sense_energy
from sense_energy import Senseable
print ("Initating connection to Sense...")
sense = Senseable(wss_timeout=30,api_timeout=30)
sense.authenticate(username, sensepass)

# pip3 install teslapy
import teslapy

# pip3 install senselink
from senselink import SenseLink
from senselink.plug_instance import PlugInstance
from senselink.data_source import MutableSource

# pip3 install tplink-cloud-api
from tplinkcloud import TPLinkDeviceManager, TPLinkDeviceManagerPowerTools


def printerror(error, err) :                               # Error message with truncated data
    print(str(err).split("}")[0], "}\n", datetime.datetime.now().strftime( "%a %I:%M %p" ), error)

def printmsg(msg) :                                        # Timestamped message
    print( " ", datetime.datetime.now().strftime( "%a %I:%M %p" ), msg )
    
def PrintUpdate(chargedata, fast) :                        # Display stats at every % change
    print( "\nLevel:",
        chargedata['battery_level'], "%, Limit",
        chargedata['charge_limit_soc'], "%,",
        chargedata['charge_rate'], "MPH",
        chargedata['charger_voltage'], "Volts",
        chargedata['charge_energy_added'], "kWh added,")
    if fast : print("Rate:",
        chargedata['charger_power'], "KWs",
        chargedata['conn_charge_cable'],
        chargedata['fast_charger_type'],
        chargedata['minutes_to_full_charge'], "Minutes remaining\n" )
    else : print(chargedata['charger_actual_current'], "of a possible",
        chargedata['charge_current_request_max'], "Amps,",
        chargedata['time_to_full_charge'], "Hours remaining\n" )
        
def PrintTemp(car) :
    if car.get_latest_vehicle_data()['climate_state']['inside_temp'] > 40 : # 104°F
        if not car.get_latest_vehicle_data()['vehicle_state']['fd_window'] : # Not Open
            Vent(car, 'vent')
    else :
        if car.get_latest_vehicle_data()['vehicle_state']['fd_window'] :    # Open
            Vent(car, 'close')
    print(car.temp_units(car.get_latest_vehicle_data()['climate_state']['inside_temp']), end=' ')
    if car.get_latest_vehicle_data()['climate_state']['fan_status'] : print(car.get_latest_vehicle_data()['climate_state']['fan_status'], end=' ')
    if car.get_latest_vehicle_data()['climate_state']['cabin_overheat_protection_actively_cooling'] : print(car.get_latest_vehicle_data()['climate_state']['cabin_overheat_protection_actively_cooling'], end=' ')

def SendCmd(car, cmd, err) :                               # Start or Stop charging
    try :
        car.command(cmd)
    except teslapy.VehicleError as e :
        print(err)
        printmsg(e)

def SetAmps(car, newrate, err) :                           # Increase or decrease charging rate
    try :
        car.command('CHARGING_AMPS', charging_amps = newrate)
    except teslapy.VehicleError as e : printerror("V: "+err, e)
    except teslapy.HTTPError as e: printerror("H: "+err, e)

def SetCharging(car, newrate, msg) :
    print(msg, "charging to", newrate, "amps")
    if newrate == 2 : newrate = 1                          # if set to 2 needs to be set to 1 to work
    SetAmps(car, newrate, "Failed to change")              #  or you will get 3 when executed
    if newrate < 5 :                                       # if under 5 amps you need to send it twice:
        SetAmps(car, newrate, "Failed to change 2")

def StartCharging(car) :
    try :                                                  # Collect new data from Tesla
        state = car.get_vehicle_data()['charge_state']['charging_state']
    except teslapy.HTTPError as e:
        printerror("Tesla failed to update, please wait a minute...", e)
        return
    print("\033[102mStarting\033[0m charge at 2 Amps")   # Underlined
    if state != "Charging" :
        SendCmd(car, 'START_CHARGE', "Won't start charging")
        SetAmps(car, 1, "Won't start charging 2")
        SetAmps(car, 1, "Won't start charging 3")

def StopCharging(car) :
    print( "\033[101m;Stopping\033[0m charge" )               # Underlined
    SendCmd(car, 'STOP_CHARGE', "Failed to stop")

def SuperCharging(chargedata) :                            # Loop while DC Fast Charging
    if chargedata['fast_charger_present']:
        printmsg("DC Fast Charging...")
        PrintUpdate(chargedata, 1)
        return(True)
        
def UpdateSense() :                                        # Update Sense info via Sense API
    global power_diff, volts
    try :
        sense.update_realtime()
    except :
        printmsg("\033[31mSense Timeout\033[m")
        power_diff = 0
        return(True)
    else :
        volts = int(sense.active_voltage[0] + sense.active_voltage[1])
        asp = int(sense.active_solar_power)
        ap = int(sense.active_power)
        power_diff = asp-ap                                # Watts being sent back to the grid
        
def Vent(car, command) :
    print("\033[31mWindows will now", command, "\033[m")
    try :
        car.command('WINDOW_CONTROL', command = command, lat=lat, lon=lon)
    except teslapy.VehicleError as e : printerror("V: ", e)
    except teslapy.HTTPError as e : printerror("H: ", e)

def Wake(car) :
    printmsg("Waking...")
    try : car.sync_wake_up()
    except teslapy.VehicleError as e :
        printerror("Failed to wake", e)
        return(False)
    return(True)

async def TesSense() :
    global mutable_plug
    rate = newrate = limit = level = lastime = fullORunplugged = 0
    minrate = 2                                            # Minimum rate you can set the charger to

    retry = teslapy.Retry(total=3, status_forcelist=(500, 502, 503, 504))
    with teslapy.Tesla(username, retry=retry, timeout=20) as tesla:
        vehicles = tesla.vehicle_list()
        
        if vehicles[0].get_vehicle_summary()['in_service'] :
            print("Sorry. Currently this car is in for service")
            exit()
            
        print("Starting connection to", vehicles[0].get_vehicle_summary()['display_name']+"... (",          round(vehicles[0].get_latest_vehicle_data()['drive_state']['latitude'], 3), round(vehicles[0].get_latest_vehicle_data()['drive_state']['longitude'], 3), ")\n")

        while (True):                                      # Main loop with night time carve out
            if datetime.datetime.now().time().hour < 8 or datetime.datetime.now().time().hour >= 20 :
                if round(vehicles[0].get_latest_vehicle_data()['drive_state']['latitude'], 3) == lat and \
                   round(vehicles[0].get_latest_vehicle_data()['drive_state']['longitude'], 3) == lon :
                    printmsg("\033[34mNighttime\033[m, Sleeping until next hour...")
                    await asyncio.sleep(60 * (60 - datetime.datetime.now().time().minute))
                    continue
                    
            if UpdateSense() :                             # Collect new data from Energy Monitor
                await asyncio.sleep(20)                    # Error: Return to top of order
                continue

            minwatts = minrate * volts                     # Calc minwatts needed to start charging
                
            if not vehicles[0].available() :               # Check if car is sleeping i.e. not available()
                if power_diff > minwatts and not fullORunplugged :
                    if Wake(vehicles[0]):                  # Initial daytime wake() also, to get status
                        rate = newrate = 0                 # Reset rate as things will have changed
                        continue
                    else:
                        print("Wake error. Sleeping 20 minutes and trying again")
                        await asyncio.sleep(1200)          # Give the API a chance to find the car
                        continue
                else : print("Sleeping, free power is", power_diff, "watts" )
                
            else :                                         # Car is awake
                try :
                    cardata = vehicles[0].get_vehicle_data() # Collect new data from Tesla
                except teslapy.HTTPError as e:
                    printerror("Tesla failed to update, please wait a minute...", e)
                    await asyncio.sleep(60)                # Error: Return to top of order
                    continue

                chargedata = cardata['charge_state']
                    
                if SuperCharging(chargedata) :             # Display any Supercharging or DCFC data
                    await asyncio.sleep(120)               # Loop while Supercharging back to top
                    continue
                    
                if round(cardata['drive_state']['latitude'], 3) != lat and \
                   round(cardata['drive_state']['longitude'], 3) != lon :
                    try :
                        Superchargers = vehicles[0].get_nearby_charging_sites()['superchargers']
                    except teslapy.HTTPError as e :
                        printerror("Failed to get local Superchargers, please wait 5 minutes...", e)
                    printmsg(str(round(Superchargers[0]['distance_miles'])) + ' mile(s) from ' + Superchargers[0]['name'] + '. Wait 5 minutes')
                    await asyncio.sleep(300)               # Prevent remote charging issues
                    continue

                if not chargedata['charging_state'] == "Charging" : # Not charging, check if need to start
                    mutable_plug.data_source.power = 0     # Let Sense know we are not charging
                    if power_diff > minwatts and not fullORunplugged: # Minimum free watts to start charge
                        if chargedata['battery_level'] >= chargedata['charge_limit_soc'] :
                            print("Full Battery, power at", power_diff, "watts" )
                            fullORunplugged = 1
                        elif chargedata['charging_state'] == "Disconnected":
                            print("\033[31mPlease plug in\033[m, power at", power_diff, "watts" )
                            fullORunplugged = 2
                        else :                             # Plugged in and battery is not full so
                            StartCharging(vehicles[0])
                            mutable_plug.data_source.power = 2 * volts
                    else :
                        print( "Not Charging, usage is at", power_diff, "watts" )

                else :                                     # Charging, update status
                    if chargedata['battery_level'] < chargedata['charge_limit_soc'] :
                        fullORunplugged = 0                # Mark it as NOT full and AS plugged-in

                    if  level != chargedata['battery_level'] or limit != chargedata['charge_limit_soc'] :
                        level, limit = chargedata['battery_level'], chargedata['charge_limit_soc']
                        PrintUpdate(chargedata, 0)         # Display charging info every % change
                        
                    rate = chargedata['charger_actual_current']
                    newrate = min(rate + int(power_diff/volts), chargedata['charge_current_request_max'])
                                                           
                    print( "Charging at", rate, "amps, with", power_diff, "watts surplus" )

                    if newrate < minrate :                 # Stop charging as there's no free power
                        StopCharging(vehicles[0])
                        newrate = 0
                    elif newrate > rate :                  # Charge faster with any surplus
                        SetCharging(vehicles[0], newrate, "Increasing")
                    elif newrate < rate :                  # Charge slower due to less availablity
                        SetCharging(vehicles[0], newrate, "Slowing")
                    mutable_plug.data_source.power = newrate * volts # Update Sense with current info (Ha!)

            if lastime != vehicles[0].get_latest_vehicle_data()['climate_state']['timestamp'] :
                lastime = vehicles[0].get_latest_vehicle_data()['climate_state']['timestamp']
                PrintTemp(vehicles[0])                     # Display cabin temp and fan use
            printmsg(" Wait two minutes...")               # Message after every complete loop
            await asyncio.sleep(120)                       # Fastest the Sense API will update is 30 sec.
            

async def CheckTPLink() :                       # Based on github.com/piekstra/tplinkcloud-service
    global output

    def printmsg(msg) :                         # Wrap a balloon around each output from CheckTPLink()
        print("=" * len(msg))
        print(msg)
        print("-" * len(msg))
    
    printmsg("Looking for TPLink smartplugs")
    device_manager = TPLinkDeviceManager(username, TPassword)
    power_manager  = TPLinkDeviceManagerPowerTools(device_manager)
    devices = await power_manager.get_emeter_devices()
    if not devices : printmsg("No TPLink (KASA) E-Meter devices found")
    else :
        print("="*72)
        print("Found "+str(len(devices))+" TP-Link E-Meter devices:")
        for i, device in enumerate(devices, 1) :
            print('{:25}'.format(device.device_info.alias), end='' if i % 3 else '\n')
        if i % 3: print()
        print("\nControlled devices:")
        for nameddevice in controllist :
            device = await power_manager.get_devices_power_usage_realtime(nameddevice)
            unit = await device_manager.find_device(nameddevice)
            if unit.device_info.status :
                print(nameddevice + " watts = " + str(round(device[0].data.power_mw)))
            else : print(nameddevice + " = offline")
        print("-"*72)
        thishour = datetime.datetime.now().time().hour
        while(True) :
            if datetime.datetime.now().time().hour < 8 :
                printmsg("\033[34mNighttime\033[m, Sleeping until morning...")
                await asyncio.sleep(60 * (60 - datetime.datetime.now().time().minute))
                await asyncio.sleep(3600 * 8 - (3600 * datetime.datetime.now().time().hour))
                continue
            if thishour != datetime.datetime.now().time().hour :
                thishour = datetime.datetime.now().time().hour
                printmsg(str(thishour-12 if thishour > 12 else thishour) + " o'clock")
            output = ''
            for nameddevice in controllist :
                UpdateSense()
                try:
                    unit = await device_manager.find_device(nameddevice)
                except:
                    printmsg("Cannot find TPLink device", nameddevice, "Please wait a minute")
                    await asyncio.sleep(60)
                    continue
                if unit.device_info.status :                    # Check if unit is online
                    try:
                        device = await power_manager.get_devices_power_usage_realtime(nameddevice)
                    except:
                        printmsg("Cannot find TPLink device status")
                        await asyncio.sleep(60)
                        continue
                    if hasattr(device[0].data, 'voltage_mv') :
                        if device[0].data.voltage_mv > 1000 :
                            factor = 1000                       # If old model data
                        else : factor = 1                       # If new model data
                        watts = device[0].data.power_mw/factor  # Convert to actual watts figure
                                # Power on nameddevice if there is 1000 watts free solar
                        if await unit.is_off() and power_diff > 1000 :
                            printmsg("\033[102mPowering on:\033[0m " + nameddevice)
                            await unit.power_on()
                                # Power off nameddevice if it is using more than 5 watts and
                                # available power isn't covering at least 2/3rds of it's usage
                        elif watts > 5 and power_diff < -(watts/3) :
                            printmsg("\033[101mPowering off:\033[0m "+ nameddevice + " because " + str(power_diff) + " is less than " + str(-(round(watts/3))) + " threshold")
                            await unit.power_off()
                        elif watts > 5 :
                            if output != '' : output = output + "\n"
                            output = output + nameddevice + " = " + str(round(device[0].data.voltage_mv/factor, 2)) + " volts, " + str(round(device[0].data.power_mw/factor,2)) +    " watts, " + str(round(device[0].data.current_ma/factor,2)) +  " amps, "+ str(round(device[0].data.total_wh/factor,2)) +    " 7-day kWhs"

            if output != '' :
                print("=" * 72)
                print(output)
                print("-" * 72)
            await asyncio.sleep(120)


async def main():                                          # Much thanks to cbpowell for this SenseLink code:
    global mutable_plug
    # Create controller, with NO config
    controller = SenseLink(None)
    
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
    tasks.add(tes_task)                             # Spawn the TesSense() function as a coroutine
    if controllist : tasks.add(tp_task)             # Spawn the CheckTPLink() function also
    tasks.add(controller.server_start())

    logging.info("Starting SenseLink controller")
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n Interrupt received, stopping SenseLink\n")
