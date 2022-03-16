import asyncio, sys, logging

import datetime
from time import sleep

# To install support module:
# Python3 -m pip install sense_energy
from sense_energy import Senseable

# Python3 -m pip install senselink
from senselink import SenseLink

# Python3 -m pip install teslapy
import teslapy

username = 'elon@tesla.com'         # Sense's and Tesla's login
password = 'password'               # Sense's password, Tesla will prompt for it's own

"""
 TesSense w/ AsyncIO  -Randy Spencer 2022 Version 5
 Python charge monitoring utility for those who own the Sense Energy Monitor.
 Uses the stats for Production and Utilization of electricity to control
 your main Tesla's AC charging to use excess production only when charging.
 Simply plug in your car, update your info above, and type> python3 tessense.py

 Added: reporting the Tesla's charging to Sense as if plugged into a TP-Link/Kasa
 Add: read & display the watts usage of the other EV charging from the HS-110
 Add: ability to find TP-Link devices on the network and control them.
"""

print ("Initating connection to Sense...")
sense = Senseable(wss_timeout=30,api_timeout=30)
sense.authenticate(username, password)

#/c Set stdout as logging handler
root_log = logging.getLogger()
root_log.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)

def printmsg(msg) :                                        # Timestamped message
    print( " ", datetime.datetime.now().strftime( "%a %I:%M %p" ), msg )
    
def printerror(error, err) :                               # Error message with truncated data
    print(str(err).split("}")[0], "}\n", datetime.datetime.now().strftime( "%a %I:%M %p" ), error)


def UpdateSense() :                                        # Update Sense info
    global power_diff
    try :
        sense.update_realtime()
    except :
        printmsg("Sense Timeout")
        return(True)
    else :
        asp = int(sense.active_solar_power)
        ap = int(sense.active_power)
        power_diff = asp-ap                                # Watts being set back to the grid

def UpdateTesla(car) :                                     # Grab the latest charge info from the Tesla
    global chargedata
    try :
        chargedata = car.get_vehicle_data()['charge_state']
    except teslapy.HTTPError as e:
        printerror("Tesla failed to update, please wait a minute...", e)
        return(True)

def PrintUpdate(fast) :
    global batlvl
    if batlvl != chargedata['battery_level'] : # Display stats at every % change
        batlvl = chargedata['battery_level']
        print( "\nLevel:",
            chargedata['battery_level'], "%, Limit",
            chargedata['charge_limit_soc'], "%, Rate is",
            chargedata['charge_amps'], "of a possible",
            chargedata['charge_current_request_max'], "Amps,",
            chargedata['charger_voltage'], "Volts, ",
            chargedata['charge_energy_added'], "kWh added, ", end="")
        if not fast : print(chargedata['time_to_full_charge'], "Hours remaining\n" )
        else : print(chargedata['minutes_to_full_charge'], "Minutes remaining\n" )

def CheckSuperCharging() :
    if chargedata['fast_charger_present']:                 # Loop while DC Fast Charging
        printmsg("Supercharging...")
        PrintUpdate(True)
        return(True)

def UpdateACcharging() :                                   # AC Charging so collect charging info
    global volts, rate, maxrate, newrate, mutable_plug
    volts =   chargedata['charger_voltage']
    rate =    chargedata['charge_current_request']
    maxrate = chargedata['charge_current_request_max']
    newrate = min( rate + int( power_diff / volts ), maxrate )
    mutable_plug.data_source.power = rate * volts      # For times when rate changes outside this app
    mutable_plug.data_source.voltage = volts
    if -2 < newrate < minrate : newrate = 0                  # Deadzone where charger is on at zero amps
        
def SendCmd(car, cmd, err) :                               # Start or Stop charging
    try :
        car.command(cmd)
    except teslapy.VehicleError as e : printerror(err, e)
    except teslapy.HTTPError as e: printerror(err, e)

def SetAmps(car, amps, err) :                              # Increase or decrease charging rate
    try :
        car.command('CHARGING_AMPS', charging_amps = amps)
    except teslapy.VehicleError as e : printerror(err, e)
    except teslapy.HTTPError as e: printerror(err, e)

def ChangeCharging(car, msg) :
    print( msg, "charging to", newrate, "amps" )
    SetAmps(car, newrate, "Failed to change")
    if newrate < 5 : SetAmps(car, newrate, "Failed to change 2")
    rate = newrate
    mutable_plug.data_source.power = rate * volts

def StopCharging(car) :
    print( "Stopping charge" )
    SendCmd(car, 'STOP_CHARGE', "Failed to stop")
    mutable_plug.data_source.power = rate * volts

def StartCharging(car) :
    global newrate, rate, volts
    if chargedata['charging_state'] == "Disconnected":
        printmsg("Please plug in")
        return(True)
    elif chargedata['battery_level'] >= chargedata['charge_limit_soc'] :
        printmsg("Full Battery")
        return(True)
    elif chargedata['charging_state'] != "Charging" :
        print( "Starting charge")
        SendCmd(car, 'START_CHARGE', "Won't start charging")
        SetAmps(car, newrate, "Won't start charging 2")        # Set the Amps twice for values under 5 amps
        if newrate < 5 : SetAmps(car, newrate, "Won't start charging 3")
        rate = newrate
        mutable_plug.data_source.power = rate * volts
        
def Wake(car) :
    print("Waking...")
    try : car.sync_wake_up()
    except teslapy.VehicleError as e : printerror("Won't wake up", e)
    except teslapy.HTTPError as e: printerror("Failed to wake", e)

async def run_tes_sense(mutable_plug):
    global batlvl, rate, newrate, minrate, maxrate, volts
    batlvl = rate = minrate = 3                                # Minimum rate you want to set the charger to
    volts = 120                                                # Minimum volts, until detected by the Tesla

    with teslapy.Tesla(username) as tesla:
        vehicles = tesla.vehicle_list()
        car = vehicles[0].get_vehicle_summary()
        print("Starting connection to", car['display_name']+"...\n")
            
        while (True):
            if UpdateSense() :                             # Collect new data from Energy Monitor
                await asyncio.sleep(20)
                continue
            if vehicles[0].available() :                   # Check if car is online
                if UpdateTesla(vehicles[0]) :              # Collect new data from Tesla
                    await asyncio.sleep(60)
                    continue
                if CheckSuperCharging() :                  # Display any Supercharging or DCFC data
                    await asyncio.sleep(120)
                    continue
                UpdateACcharging()                         # Collect AC Charging data from Tesla
                if chargedata['charging_state'] == "Charging" :# Check if need to change rate or stop
                    PrintUpdate(False)
                    if power_diff > 1 :                    # Enough free power to continue
                        print( "Charging at", rate, "amps, with", power_diff, "watts surplus" )
                    elif power_diff < -1 :                 # Not enough free power to continue
                        print( "Charging at", rate, "amps, with", power_diff, "watts usage" )
                    else : print( "Charging at", rate, "amps" ) # power_diff = -1, 0 or 1, so don't say "watts"
                    if newrate < 0 :                       # Stop charging if there's no free power
                        StopCharging(vehicles[0])
                    elif newrate > rate :                  # Charge faster with any surplus
                        ChangeCharging(vehicles[0], "Increasing")
                    elif newrate < rate :                  # Charge slower due to less availablity
                        ChangeCharging(vehicles[0], "Slowing")
                    else :
                        mutable_plug.data_source.power = rate * volts
                else :                                     # Not charging, check if need to start
                    print( "Not Charging, Spare power at", power_diff, "watts" )
                    if power_diff > ( minrate * volts ) :  # Minimum free watts to wake car and charge
                        if StartCharging(vehicles[0]) :
                            await asyncio.sleep(180)
                            continue
            else :                                         # Sleeping, check if need to wake and charge
                print("Sleeping, free power is", power_diff, "watts" )
                if power_diff > ( minrate * volts ) :
                    Wake(vehicles[0])
                    continue
            printmsg(" Wait two minutes...")               # Message every loop
            await asyncio.sleep(120)                       # Fastest the Sense API will update is 30 sec.


async def main():
    global mutable_plug
    # Get config
    config = open('config.yml', 'r')
    # Create controller, with config
    controller = SenseLink(config)
    # Create instances
    controller.create_instances()

    # Get Mutable controller object, and create task to update it
    mutable_plug = controller.plug_for_mac("53:75:31:f8:3a:8c")

    # Pass plug to TesSense, where TesSense can update it
    tes_task = run_tes_sense(mutable_plug)

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
