"""
 TesSense w/ SenseLink  -Randy Spencer 2023 Version 9.7
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

username = 'elon@tesla.com'             # Sense's and TPLink's and Tesla's login
sensepass = 'sense password'            # Sense's password, Tesla will prompt for it's own
TPassword = 'TPLink password'           # TPLink's password
lat, lon  = 38, -122                    # Location where charging will occur (shown at startup)
controllist = 0 #["Lamp", "TV", "Heater"]  # Replace '0' with a list of named devices to control

RedTxt, BluTxt, NormTxt = '\033[31m', '\033[34m', '\033[m'
RedBG, GrnBG, NormBG = '\033[101m', '\033[102m', '\033[0m'

import datetime, asyncio
import logging, sys#, json
#/c Set stdout as logging handler
root_log = logging.getLogger()
root_log.setLevel(logging.WARNING) # WARNING or INFO or DEBUG
handler = logging.StreamHandler(sys.stdout)

# To install support module:
# pip3 install sense_energy
from sense_energy import Senseable

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
    
def PrintTemp(car) :
    if car.get_vehicle_data()['climate_state']['inside_temp'] > 40 : # 104°F
        if not car.get_vehicle_data()['vehicle_state']['fd_window'] : # Not Open
            Vent(car, 'vent')
    else :
        if car.get_vehicle_data()['vehicle_state']['fd_window'] :    # Open
            Vent(car, 'close')
    print(car.temp_units(car.get_vehicle_data()['climate_state']['inside_temp']), end='')
    if car.get_vehicle_data()['climate_state']['fan_status'] : print(car.get_vehicle_data()['climate_state']['fan_status'], end='')
    if car.get_vehicle_data()['climate_state']['cabin_overheat_protection_actively_cooling'] : print(car.get_vehicle_data()['climate_state']['cabin_overheat_protection_actively_cooling'], end='')

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
    if newrate == 2 : newrate = 1                          # For API a newrate of 3=3, 2=3, 1=2
    SetAmps(car, newrate, "Failed to change")              #  so to set to 2 newrate must be 1
    if newrate < 5 :                                       # if under 5 amps you need to send it twice:
        SetAmps(car, newrate, "Failed to change 2")

def StartCharging(car) :
    try :                                                  # Collect new data from Tesla
        state = car.get_vehicle_data()['charge_state']['charging_state']
    except teslapy.HTTPError as e:
        printerror("Tesla failed to update, please wait a minute...", e)
        return
    print(GrnBG + "Starting" + NormBG + " charge at 2 Amps")     # Underlined
    if state != "Charging" :
        SendCmd(car, 'START_CHARGE', "Won't start charging")
        SetAmps(car, 1, "Won't start charging 2")
        SetAmps(car, 1, "Won't start charging 3")

def StopCharging(car) :
    print( RedBG + "Stopping" + NormBG + " charge" )            # Underlined
    SendCmd(car, 'STOP_CHARGE', "Failed to stop")

def SuperCharging(chargedata) :                            # Loop while DC Fast Charging
    if chargedata['fast_charger_present']:
        printmsg("DC Fast Charging...")
        PrintUpdate(chargedata, 1)
        return(True)
        
def UpdateSense() :                                        # Update Sense info via Sense API
    global power_diff, volts
    try :
        sense.update_trend_data()
        sense.update_realtime()
    except :
        printmsg(RedTxt + "Sense Timeout" + NormTxt)
        power_diff = 0
        return(True)
    else :
        volts = int(sense.active_voltage[0] + sense.active_voltage[1])
        power_diff = int(sense.active_solar_power - sense.active_power)
        
def Vent(car, command) :
    try :  car.command('WINDOW_CONTROL', command = command, lat=lat, lon=lon)
    except teslapy.VehicleError as e : printmsg("Window_Control Failed " + str(e))
    else:  print(RedTxt + "Windows will now", command + NormTxt)

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

    print ("Initating connection to Sense...")
    sense = Senseable(wss_timeout=30,api_timeout=30)
    sense.authenticate(username, sensepass)

    retry = teslapy.Retry(total=3, status_forcelist=(500, 502, 503, 504))
    with teslapy.Tesla(username, retry=retry, timeout=30) as tesla:
        vehicles = tesla.vehicle_list()

        print("Starting connection to", vehicles[0].get_vehicle_summary()['display_name'], end='')
        cardata = vehicles[0].get_vehicle_data()
        try:
            print("... [", round(cardata['drive_state']['latitude'], 3), round(cardata['drive_state']['longitude'], 3), "]")
        except: pass
        print(' last seen ' + vehicles[0].last_seen(), end='')
        if vehicles[0]['charge_state']['battery_level']:
            print(' at ' + str(vehicles[0]['charge_state']['battery_level']) + '% SoC\n')
        else: print('\n')

        while (True):                                      # Main loop with night time carve out
            if vehicles[0].get_vehicle_summary()['in_service'] :
                print("Sorry. Currently this car is in for service")
                exit()
        
            if datetime.datetime.now().time().hour < 8 or datetime.datetime.now().time().hour >= 20 :
                printmsg(BluTxt + "Nighttime" + NormTxt +", Sleeping until next hour...")
                await asyncio.sleep(60 * (60 - datetime.datetime.now().time().minute))
                continue

            if UpdateSense() :                             # Collect new data from Energy Monitor
                await asyncio.sleep(20)                    # Error: Return to top of order
                continue

            minwatts = minrate * volts                     # Calc minwatts needed to start charging
                
            if not vehicles[0].available() :               # Car is sleeping
                if power_diff > minwatts and not fullORunplugged :
                    if Wake(vehicles[0]):                  # Initial daytime wake() also, to get status
                        rate = newrate = 0                 # Reset rate as things will have changed
                        continue
                    else:
                        print("Wake error. Sleeping 20 minutes and trying again")
                        await asyncio.sleep(1200)          # Give the API a chance to find the car
                        continue
                else :
                    if fullORunplugged == 1 : print("Full-", end='')
                    elif fullORunplugged == 2 : print("Unplugged-", end='')
                    print("Sleeping, free power is", power_diff, "watts" )
                    if fullORunplugged :
                        printmsg(" Wait twenty minutes...")
                        await asyncio.sleep(1200)
                        continue

            else :                                         # Car is awake
                try :
                    cardata = vehicles[0].get_vehicle_data() # Collect new data from Tesla
                    chargedata = cardata['charge_state']
                except teslapy.HTTPError as e:
                    printerror("Tesla failed to update, please wait a minute...", e)
                    await asyncio.sleep(60)                # Error: Return to top of order
                    continue

                if SuperCharging(chargedata) :             # Display any Supercharging or DCFC data
                    await asyncio.sleep(120)               # Loop while Supercharging back to top
                    continue

                if 'latitude' in cardata['drive_state'] :  # Prevent remote charging issues
                    if round(cardata['drive_state']['latitude'], 3) != lat and \
                       round(cardata['drive_state']['longitude'], 3) != lon :
                        print(round(cardata['drive_state']['latitude'], 3), \
                             round(cardata['drive_state']['longitude'], 3), end='')
                        printmsg(' Away from home. Wait 5 minutes')
                        fullORunplugged = 2                 # If it's not at home, it's not plugged in nor full
                        await asyncio.sleep(300)
                        continue
                else :
                    print(RedTxt + 'Error: No Location' + NormTxt)
                    
                if not chargedata['charging_state'] == "Charging" :   # Not charging, check if need to start
                    mutable_plug.data_source.power = 0                # Let Sense know we are not charging
                    if power_diff > minwatts and not fullORunplugged: # Minimum free watts to start charge
                        if chargedata['battery_level'] >= chargedata['charge_limit_soc'] :
                            print("Full Battery, power at", power_diff, "watts" )
                            fullORunplugged = 1
                        elif chargedata['charging_state'] == "Disconnected":
                            print(RedTxt + "Please plug in" + NormTxt + ", power at", power_diff, "watts" )
                            fullORunplugged = 2
                        else :                             # Plugged in and battery is not full so
                            StartCharging(vehicles[0])
                            mutable_plug.data_source.power = 2 * volts
                    else :
                        print( "Not Charging, free power is at", power_diff, "watts" )

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

            if lastime != vehicles[0].get_vehicle_data()['climate_state']['timestamp'] :
                lastime = vehicles[0].get_vehicle_data()['climate_state']['timestamp']
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
                print(nameddevice + " watts = " + str(round(device[0].data.power_mw))) #**** Something isn't working ****
            else : print(nameddevice + " = offline")
        print("-"*72)
        thishour = datetime.datetime.now().time().hour
        while(True) :
            # Sleep until 8 am
            if datetime.datetime.now().time().hour < 8 :
                printmsg(BluTxt + "Nighttime" + NormTxt + ", Sleeping until morning...")
                await asyncio.sleep(60 * (60 - datetime.datetime.now().time().minute))
                await asyncio.sleep(3600 * 8 - (3600 * datetime.datetime.now().time().hour))
                continue
            # Announce on top of the hour to be sure process is still running
            if thishour != datetime.datetime.now().time().hour :
                thishour = datetime.datetime.now().time().hour
                printmsg(str(thishour-12 if thishour > 12 else thishour) + " o'clock")
                
            try:
                unit = await device_manager.find_device(nameddevice)
            except:
                printmsg("Cannot find TPLink device", nameddevice, "Please wait a minute")
                await asyncio.sleep(60)
                continue
            # Build message to display if controllist devices are using much power
            output = ''
            for nameddevice in controllist :
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
                                # Power on nameddevice if there are 1000 watts free solar
                        try:
                            if await unit.is_off() and power_diff > 1000 :
                                print("="*72 + "\n" + GrnBG + "Powering on:" + NormBG + ' ' + nameddevice + "\n" + "-"*72)
                                await unit.power_on()
                                break
                                    # Power off nameddevice if it is using more than 5 watts and
                                    # solar power isn't covering at least half of it's usage
                            elif watts > 5 and power_diff < -(watts/2) :
                                print("="*72 + "\n" + RedBG + "Powering off:" + NormBG + ' ' + nameddevice + "\nBecause " + str(power_diff) + " watts is less than " + str(-(round(watts/2))) + " watts threshold\n" + "-"*72)
                                await unit.power_off()
                                break
                            elif watts > 5 :
                                if output != '' : output = output + "\n"
                                output = output + nameddevice + " = " + str(round(device[0].data.voltage_mv/factor, 2)) + " volts, " + str(round(device[0].data.power_mw/factor,2)) +    " watts, " + str(round(device[0].data.current_ma/factor,2)) +  " amps, "+ str(round(device[0].data.total_wh/factor,2)) +    " 7-day kWhs"
                        except : printmsg("Unable to communicate with TPlink " + nameddevice)

            if output != '' :
                print("=" * 72)
                print(output)
                print("-" * 72)
            #else : print("-", end='')
            await asyncio.sleep(180)


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
