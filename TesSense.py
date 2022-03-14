username = 'elon@tesla.com'         # Sense's and Tesla's login
password = 'password'               # Sense's password, Tesla will prompt for it's own

"""
 TesSense  -Randy Spencer 2022
 Python charge monitoring utility for those who own the Sense Energy Monitor
 Uses the stats for Production and Utilization of electricity to control
 your main Tesla's AC charging to use excess production only when charging.
 Simply plug in your car, update your info above, and type> python3 tessense.py

 Added: another minute to remove powering off due to spurius spikes/clouds
 Add: reporting the Tesla's charging to Sense as if plugged into a TP-Link/Kasa
 Add: ability to find TP-Link devices on the network and control them.
"""

import asyncio
import sys
import logging
import datetime
from time import sleep

# Set stdout as logging handler
root_log = logging.getLogger()
root_log.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)

def printmsg(msg) :                                   # Timestamped message
    print( datetime.datetime.now().strftime( "%a %I:%M %p" ), msg )
    
def printerror(error, err) :                          # Error message with truncated data
    print( datetime.datetime.now().strftime( "%a %I:%M %p" ), error+"\n", str(err).split("}")[0], "}" )
    
# To install support module:
# Python3 -m pip install sense_energy
print ("Initating connection to Sense...")
from sense_energy import Senseable
sense = Senseable(wss_timeout=30,api_timeout=30)
sense.authenticate(username, password)

# Python3 -m pip install senselink
from senselink import SenseLink

# Python3 -m pip install teslapy
print ("Starting connection to Tesla...")
import teslapy


async def run_tes_sense(mutable_plug):
    rate = minrate = 0  # Minimum rate you want to set the charger to
    volts = 120  # Minimum volts, until detected by the charger
    pshown = loop = charge = charging = False  # init more variables

    with teslapy.Tesla( username ) as tesla:
        if not tesla.authorized:
            tesla.refresh_token(refresh_token=input('Enter SSO refresh token: '))

        vehicles = tesla.vehicle_list()
        car = vehicles[0].get_vehicle_summary()
        print(car['display_name'], "is", car['state'], "\n")

        #print( "Tesla Info:\n", vehicles[0].get_vehicle_data(), "\n\n" ) # shows all car data available
        #print( "TeslaPy:\n", dir( teslapy ), "\n\n" )         # shows all the TeslaPy API functions
        #print( "Senseable:\n", dir( Senseable ), "\n\n" )     # shows all the Sense API functions

        while (True):
            try :
                sense.update_realtime()                   # Update Sense info
                asp = int(sense.active_solar_power)
                ap = int(sense.active_power)
                power_diff = asp-ap                       # Watts being set back to the grid
            except :
                printmsg("Sense Timeout")
                await asyncio.sleep(10)
                continue # back to the top of the order

            # Assume not charging to start
            charging = False

            if vehicles[0].available() :
                try :
                    chargedata=vehicles[0].get_vehicle_data()['charge_state']
                except teslapy.HTTPError as e:
                    printerror("Tesla failed to update, please wait a minute...", e)
                    await asyncio.sleep(60)
                    continue

                if chargedata['charging_state'] == "Disconnected": # Loop w/o msgs until connected
                    if not pshown :
                        printmsg(" Please plug the vehicle in...\n\n")
                        pshown = True

                    # Set 0 watts to plug
                    mutable_plug.data_source.power = 0
                    await asyncio.sleep(60)
                    continue
                else : pshown = False

                if chargedata['battery_level'] >= chargedata['charge_limit_soc'] : # Loop when full
                    # Set 0 watts to plug
                    mutable_plug.data_source.power = 0
                    print ("Full Battery!")
                    await asyncio.sleep(60)
                    continue

                if chargedata['fast_charger_present']:    # Loop while DC Fast Charging
                    printmsg("Supercharging...")
                    if charge != chargedata['battery_level'] :
                        charge = chargedata['battery_level']
                        print( "\nLevel:",
                            chargedata['battery_level'], "%, Limit",
                            chargedata['charge_limit_soc'], "%, Rate",
                            chargedata['charger_power'], "kW, ",
                            chargedata['charger_voltage'], "Volts, ",
                            chargedata['fast_charger_type'],
                            chargedata['minutes_to_full_charge'], "Minutes remaining\n" )

                    # Set 0 watts to plug
                    mutable_plug.data_source.power = 0
                    await asyncio.sleep(60)
                    continue

                if chargedata['charging_state'] == "Charging": # Collect charging info
                    volts =   chargedata['charger_voltage']
                    rate =    chargedata['charge_current_request']
                    maxrate = chargedata['charge_current_request_max']
                    newrate = min( rate + int( power_diff / volts ), maxrate )
                    if newrate == 1 or newrate == 2 : newrate = 0
                    charging = True
                else:
                    charging = False


            if charging :                                 # check if need to change rate or stop
                if power_diff > 1 :
                    print( "Charging at", rate, "amps, with", power_diff, "watts surplus" )
                    if newrate > rate :
                        print( "Increasing charging to", newrate, "amps" )
                        try :
                            vehicles[0].command( 'CHARGING_AMPS', charging_amps = newrate )
                            if newrate < 5 : vehicles[0].command( 'CHARGING_AMPS', charging_amps = newrate )
                            rate = newrate
                            # Set plug power to new power?
                            # mutable_plug.data_source.power = ...
                        except teslapy.VehicleError as e : printerror("Error up", e)
                        except teslapy.HTTPError as e: printerror("Failed up", e)

                elif power_diff < -1 :                    # Not enough free power to continue charging
                    print( "Charging at", rate, "amps, with", power_diff, "watts usage" )
                    if newrate < minrate:                 # Stop charging when below minrate
                        if not loop :
                            print("Just Once More")       # Delay powering off once for suprious data
                            loop = True
                        else :
                            print( "Stopping charge" )
                            try :
                                vehicles[0].command( 'STOP_CHARGE' )
                                # Set plug power to 0?
                                # mutable_plug.data_source.power = 0
                            except teslapy.VehicleError as e : printerror("Won't stop charging", e)
                            except teslapy.HTTPError as e: printerror("Failed to stop", e)
                            loop = False

                    elif newrate < rate :                 # Slow charging to match free solar
                        print( "Slowing charging to", newrate, "amps" )
                        try :
                            vehicles[0].command( 'CHARGING_AMPS', charging_amps = newrate )
                            if newrate < 5 : vehicles[0].command( 'CHARGING_AMPS', charging_amps = newrate )
                            rate = newrate
                            # Set plug power to new power?
                            # mutable_plug.data_source.power = ...
                        except teslapy.VehicleError as e : printerror("Error down", e)
                        except teslapy.HTTPError as e: printerror("Failed down", e)
                else :
                    print( "Charging at", rate, "amps" )  # -1, 0 or 1 watt diff, so don't say "watts"
                    # Set plug power to current power?
                    # mutable_plug.data_source.power = ...

            else :                                        # NOT Charging, check if time to start
                print( "Not Charging, Spare power at", power_diff, "watts" )
                mutable_plug.data_source.power = 10
                if power_diff > ( minrate * volts ) :     # Minimum free watts to wake car and charge
                    print( "Starting charge" )
                    try : vehicles[0].sync_wake_up()
                    except teslapy.VehicleError as e : printerror("Won't wake up", e)
                    except teslapy.VehicleError as e: printerror("Wake Timeout", e)

                    if vehicles[0].available() :
                        try :                             # Check LIVE data first
                            chargedata=vehicles[0].get_vehicle_data()['charge_state']
                            if chargedata['charging_state'] == "Disconnected":
                                print(" Please plug the vehicle in...")
                                pshown = True
                                continue
                            elif chargedata['charging_state'] != "Charging" :
                                vehicles[0].command( 'START_CHARGE' )
                                vehicles[0].command( 'CHARGING_AMPS', charging_amps=minrate )
                                vehicles[0].command( 'CHARGING_AMPS', charging_amps=minrate )
                                charging = True
                        except teslapy.VehicleError as e : print("Won't start charging", e)

            if charging :                                 # Display stats every % charge
                if charge != chargedata['battery_level'] :
                    charge = chargedata['battery_level']
                    print( "\nLevel:",
                        chargedata['battery_level'], "%, Limit",
                        chargedata['charge_limit_soc'], "%, Rate is",
                        chargedata['charge_amps'], "of a possible",
                        chargedata['charge_current_request_max'], "Amps,",
                        chargedata['charger_voltage'], "Volts, ",
                        chargedata['time_to_full_charge'], "Hours remaining\n" )

            printmsg(" Wait a minute...")
            await asyncio.sleep(60)  # The fastest the Sense API will update


async def main():
    # Get config
    config = open('config.yml', 'r')

    # Create controller, with config
    controller = SenseLink(config)
    # Create instances
    controller.create_instances()

    # Get Mutable controller object, and create task to update it
    mutable_plug = controller.plug_for_mac("50:c7:bf:f6:4f:39")

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
