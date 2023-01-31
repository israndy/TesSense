"""
 TesSense w/ SenseLink & Emporia Energy Monitor
 Randy Spencer 2022 Version 9.6
 (highly)modified by Jason Dillman 2023 Version 1.0
 Python charge monitoring utility for those who own the Sense Energy Monitor
 or Emporia Energy monitor.  Uses the stats for Production and Utilization of 
 electricity to control all of your Tesla's AC charging to charge only with excess production.
 Simply plug in your vehicle, update your info below, and type> python3 tessense.py

 Added: Compatibility with Emporia Energy meter, logic to check what energy meter you 
 have configured and use it automatically, compatibility with multiple vehicles,
 configurable option for gradually ramping down the charge rate, configurable option
 to round charge rate up if exporting more than .5 amps (useful if your export price is lower
 than your import price), changed day/night check to dynamically adjust based on sunrise
 and sunset at your location, significantly re-factored code for better readability
 including moving nearly all actions into functions and re-organizing the logic into
 a switch/case waterfall block.

 To-Do: Add overnight charging to a configurable minimum threshold, add configuration
 for peak/time of use rates, add compability with other energy monitoring solutions 
 such as the Eagle-200, Enphase Gateway, and possibly others.
 
 python .\tessense-main\tessense.py
"""

#lets do some git testing

# User variables
username                      = 'username@here.com'                 # Tesla's login
emporiaUsername               = 'username@here.com'                 # Emporias's login
sensePassword                 = 'sense password'                    # Sense's password, Tesla will prompt for it's own
tpLinkPassword                = 'TPLink password' #Not used         # TPLink's password
lat                           = 30.222                              # Location where charging will occur (shown at startup)
lon                           = -97.617                             # Location where charging will occur (shown at startup)
tpLinkDeviceList              = False #["Lamp", "TV", "Heater"]     # Replace '0' with a list of named devices to control
reportSolarProduction         = True                                # EMPORIA ONLY: Display solar production as well as excess power
emporiaSolarChannelNumber     = '1'                                 # EMPORIA ONLY: Circuit number of the Emporia channel monitoring solar, used above
ampsToStopCharging            = 2                                   # Amps the vehicle will stop charging at
ampsToStartCharging           = 5                                   # Amps the vehicle will start charging at
gradualChargeRateDecrease     = True                                # True/False | Slowly ramp down the charge rate to reduce charge start/stop cycles
roundChargeAmpUpwhenEporting  = True                                # If exporting more than .5 amps to the grid, increase the charge rate by 1 amp
ventWindowsIfOverTemperature  = False                               # True/False | Vent the windows if over ventWindowTempSetpoint
ventWindowTemperatureSetpoint = 40                                  # Temperature (in Celsius) to vent the windows if ventWindowsIfOverTemperature is True

# Imports
import asyncio, datetime, json, logging, time, sys, pytz
import teslapy # pip3 install teslapy
import timezonefinder # python -m pip install timezonefinder
from suntime                 import Sun, SunTimeException # python -m pip install suntime
from sense_energy            import Senseable # pip3 install sense_energy
from senselink               import SenseLink # pip3 install senselink
from senselink.plug_instance import PlugInstance
from senselink.data_source   import MutableSource

# Detect what services have been configured and import perform required module import and service connection
if emporiaUsername != 'username@here.com' and emporiaUsername != '' :
    emporiaConfigured = True
else :
    emporiaConfigured = False

if sensePassword != 'sense password' and sensePassword != '' and not emporiaConfigured: 
    senseConfigured = True
else :
    senseConfigured = False

if not senseConfigured and not emporiaConfigured :
    print( "===MUST CONFIGURE A POWER METER SOURCE===" )
    exit()

# Import modules for the configured services
if tpLinkPassword != 'TPLink password' and tpLinkPassword != '' and tpLinkDeviceList :
    tpLinkConfigured = True
else :
    tpLinkConfigured = False

if emporiaConfigured :
    import pyemvue # python -m pip install pyemvue
    from pyemvue.enums  import Scale, Unit

if tpLinkConfigured :
    from tplinkcloud import TPLinkDeviceManager, TPLinkDeviceManagerPowerTools # pip3 install tplink-cloud-api

#/c Set stdout as logging handler
rootLog  = logging.getLogger()
handler  = logging.StreamHandler( sys.stdout )
# WARNING or INFO or DEBUG
rootLog.setLevel( logging.WARNING )

# Initiate service connections
print ( "Initating connection to services..." )
sense = Senseable( wss_timeout=30,api_timeout=30 )

def printErrorMessage (errorMessage, fullError) :
    print( str( fullError ).split( "}" )[0], "\n", datetime.datetime.now().strftime( "%a %H:%M" ), errorMessage )

def printMessageWithTimestamp (message) :
    print( datetime.datetime.now().strftime( "%a %H:%M" ), message )

def printStatus (status, currentChargeAmps, newChargeAmps, vehicleName, volts, wattsExported) :
    if newChargeAmps - currentChargeAmps > 0 :
        rateArrow = "↑"
    elif newChargeAmps - currentChargeAmps < 0 :
        rateArrow = "↓"
    else :
        rateArrow = " "

    print( 
        datetime.datetime.now().strftime( "%a %H:%M"                                 ),
        "|"                , vehicleName                                              ,
        "| Status:"        , status.ljust(17," "                                     ),
        "| Amps:"          , str(currentChargeAmps).rjust(2, " "                     ),
        "| Amps change:"   , str(int(newChargeAmps - currentChargeAmps)).rjust(2, " "), rateArrow,
        "| Volts:"         , volts                                                    , 
        "| Watts:"         , str(int(currentChargeAmps * volts  )).rjust(5, " "      ),
        "| Watts to Grid:" , str(int(wattsExported    )).rjust(6, " "                ), 
        end= ' ' )

    if reportSolarProduction :
        print( "| Watts Solar Generation:", str(int(solarGeneration)).rjust(6, " ") )
    else :
        print( '' )

def printChargingUpdate (chargedata, vehicleIsSuperchargin) :
    print( '' )
    print(
        "Level:"                   , chargedata['battery_level'      ], "% | "  ,
        "Limit:"                   , chargedata['charge_limit_soc'   ], "% | "  , 
        "Rate:"                    , chargedata['charge_rate'        ], "MPH | ",
        "Added:"                   , chargedata['charge_energy_added'], "kWh | ",
        "Time remaining (hours): " , chargedata['time_to_full_charge'],
        "\n" )

    if vehicleIsSuperchargin : 
        print(
            "Rate:" , chargedata['charger_power'         ], 
            "KWs"   , chargedata['conn_charge_cable'     ],
                      chargedata['fast_charger_type'     ],
                      chargedata['minutes_to_full_charge'], 
            "Minutes remaining\n" 
            )

def ventWindowsIfInteriorAboveSetpoint (vehicle, latestVehicleData) :
    # If temp inside vehicle is over ventWindowTemperatureSetpoint
    if latestVehicleData['climate_state']['inside_temp'] > ventWindowTemperatureSetpoint : 
        # If windows are not Open
        if not latestVehicleData['vehicle_state']['fd_window'] : 
            sendWindowVentCommand( vehicle, 'vent' )
    else :
        # If temp inside vehicle is below ventWindowTemperatureSetpoint and the windows are open
        if latestVehicleData['vehicle_state']['fd_window'] : 
            sendWindowVentCommand( vehicle, 'close' )

def printVehicleClimateInfo (vehicle) :
    print("Cabin temp: ", vehicle.temp_units( vehicle['climate_state']['inside_temp'] ) , end=' ' )

    # If the interior fan is on print the fan status
    if vehicle['climate_state']['fan_status'] > 0 : 
        print( "Fan speed:", vehicle['climate_state']['fan_status'], end=' ' )

    # If Cabin Overheat Protection is enabled print the status 
    if vehicle['climate_state']['cabin_overheat_protection_actively_cooling'] : 
        print( "Cabin Overheat Protection: ON" )
    print( "\n" )

def sendWindowVentCommand (vehicle, command) :
    print( "Windows will now", command )

    try :
        vehicle.command( 'WINDOW_CONTROL', command = command, lat=lat, lon=lon )
    except teslapy.VehicleError as e : 
        printMessageWithTimestamp( "Window_Control Failed " + str(e) )

def sendCommandToVehicle(vehicle, cmd, err) :
    try :
        vehicle.command( cmd )
    except teslapy.VehicleError as e :
        print( err )
        printMessageWithTimestamp( e )

def sendChargingAmpsToVehicle (vehicle, newChargeAmps, err) :
    try :
        vehicle.command( 'CHARGING_AMPS', charging_amps = newChargeAmps )
    except teslapy.VehicleError as fullError : printErrorMessage( "V: "+err, fullError )
    except teslapy.HTTPError as fullError : printErrorMessage( "H: "+err, fullError )

def setChargeRateForTeslaAPI (vehicle, newChargeAmps) :    
    # For API a newChargeAmps of 3=3, 2=3, 1=2, so to set to 2 newChargeAmps must be 1
    if newChargeAmps == 2 :
        newChargeAmps = 1

    sendChargingAmpsToVehicle( vehicle, newChargeAmps, "Failed to change" )
    # If rate is under 5 amps you need to send it twice
    if newChargeAmps < 5 :
        sendChargingAmpsToVehicle( vehicle, newChargeAmps, "Failed to change 2" )

def startChargingVehicle (vehicle, currentChargeAmps) :
    # Collect new data from Tesla
    vehicleData = getVehicleData( vehicle )
    if not vehicleData :
        print( "Tesla failed to update, please wait a minute..." )
        return
    state = vehicleData['charge_state']['charging_state']

    print( "⚡Starting⚡ charge at", currentChargeAmps, "Amps" )
    if state != "Charging" :
        sendCommandToVehicle( vehicle, 'START_CHARGE', "Won't start charging" )
        sendChargingAmpsToVehicle( vehicle, currentChargeAmps, "Won't start charging 2" )
        # If rate is under 5 amps you need to send it twice
        sendChargingAmpsToVehicle( vehicle, currentChargeAmps, "Won't start charging 3" )

def stopChargingVehicle (vehicle) :
    print( "Stopping charge on",vehicle["display_name"] )
    sendCommandToVehicle( vehicle, 'STOP_CHARGE', "Failed to stop" )

# Loop while DC Fast Charging
def vehicleIsDcFastCharging (chargedata) :
    if chargedata['fast_charger_present'] :
        printMessageWithTimestamp( "DC Fast Charging..." )
        printChargingUpdate( chargedata, True )
        return ( True )
    else :
        return ( False )
        

def updatePowerUse () :
    resultsReturned = True

    while( resultsReturned ) :
        try :
            if emporiaConfigured :
                # Retrieve kWh usage for the last minute for all Emporia devices
                # Emporia names the grid connection channel '1,2,3' on my device, this may need to be changed for yours
                device_usage_dict = vue.get_device_list_usage( deviceGids=emporiaDeviceGids, instant=datetime.datetime.utcnow(), scale=Scale.MINUTE.value, unit=Unit.KWH.value )
                wattsExported     = round( ( device_usage_dict[primaryEmporiaDevice].channels['1,2,3'].usage * 60 * 1000 * -1 ) ,0 )
                
                if reportSolarProduction :
                    global solarGeneration
                    solarGeneration = round( ( device_usage_dict[primaryEmporiaDevice].channels[emporiaSolarChannelNumber].usage * 60 * 1000 * -1 ) ,0 )
            
            if senseConfigured :
                # Update Sense info via Sense API
                sense.update_realtime()

                senseActiveSolarPower = int( sense.active_solar_power )
                senseActivePower      = int( sense.active_power       )
                wattsExported         = senseActiveSolarPower-senseActivePower      

            resultsReturned = False

        except :
            printMessageWithTimestamp( "Energy meter update timeout" )
            time.sleep( 5 )
    return wattsExported
                                     
def sendWakeToVehicle (vehicle) :
    printMessageWithTimestamp( "Waking " + vehicle["display_name"] )

    try : 
        vehicle.sync_wake_up()
    except teslapy.VehicleError as fullError :
        printErrorMessage( "Failed to wake", fullError )
        return ( False )
    return ( True )

def getActiveVehicle (vehicleList) :
    i                                     = 0
    vehicleUnavailableCount               = 0
    previousVehicleRangeRemainingToCharge = 0
    activeVehicleIndex                    = 0
    noVehiclesAvailable                   = False

    # Looping through all available vehicles
    for vehicle in vehicleList :
        vehicleInfo = getVehicleData( vehicle )
        
        if not vehicleInfo :
            print( "GetActiveVehicle: Tesla failed to update", vehicle["display_name"] )
            i += 1
            continue

        vehicleChargeInfo  = vehicleInfo['charge_state']
        vehicleUnavailable = 0

        if vehicleAtHomeCheck( vehicle, vehicleInfo ) == "Away" :
            vehicleUnavailableCount += 1
            i += 1
            continue

        # If the vehicle battery is full, it is not plugged in, or it is in service, mark it as unavailable
        if vehicleChargeInfo['battery_level' ] >= vehicleChargeInfo['charge_limit_soc'] or \
           vehicleChargeInfo['charging_state'] == "Disconnected"                        or \
           vehicle.get_vehicle_summary()['in_service'] :
            
            vehicleUnavailableCount += 1
            vehicleUnavailable = 1

        # Calculate the miles of range remaining to be charged
        rangeRemainingToCharge = ( vehicleChargeInfo["battery_range"   ] / vehicleChargeInfo["battery_level"] *
                                 ( vehicleChargeInfo["charge_limit_soc"] - vehicleChargeInfo["battery_level"] ) )

        if rangeRemainingToCharge > previousVehicleRangeRemainingToCharge and \
           not vehicleUnavailable :
            previousVehicleRangeRemainingToCharge = rangeRemainingToCharge
            activeVehicleIndex                    = i
        
        i += 1

    # If every vehicle checked is unavailable set the "noVehiclesAvailable" flag
    if vehicleUnavailableCount == i :
        noVehiclesAvailable = True
        print( "All vehicles unavailable for charging." )
    return vehicleList[activeVehicleIndex], noVehiclesAvailable

def calculateNightSleepSeconds (sun,tz) :
    try :
        utcOffsetHours = datetime.timedelta( hours = ( datetime.datetime.now( pytz.timezone(tz) ).utcoffset().total_seconds()/60/60 ) )
        sunriseTime    = ( sun.get_sunrise_time() + utcOffsetHours ).time()
        sunsetTime     = ( sun.get_sunset_time()  + utcOffsetHours ).time()
    except :
        seconds = 0
        return seconds
    
    now                     = datetime.datetime.now()
    tomorrowSunriseDatetime = datetime.datetime.combine( datetime.datetime.date(now) , sunriseTime ) + datetime.timedelta( days = 1 )

    # Due to UTC vs local, sometimes sunrise/sunset may be returned as the next or previous day.  To resolve this we only compare the time.
    if now.time() > sunsetTime or now.time() < sunriseTime :
        seconds = ( tomorrowSunriseDatetime - now ).total_seconds()
    else :
        seconds = 0
    return seconds, sunriseTime

def calculateNewChargeRate (rate, chargeData, newChargeAmps, wattsExported, volts) :
    currentChargeAmps = chargeData['charger_actual_current']
    newChargeAmps     = min( currentChargeAmps + int(wattsExported/volts), chargeData['charge_current_request_max'] )

    if roundChargeAmpUpwhenEporting :
        # If exporting more than .5 amps to the grid, increase the charge rate by 1 amp
        # This is because of my electric co-op's crap export rate
        if wattsExported > volts / 2 and wattsExported < volts :
            newChargeAmps += 1

    if gradualChargeRateDecrease :
        rateMaxDecrease = int( round( currentChargeAmps * .66,0 ) )
        if newChargeAmps < rateMaxDecrease :
            newChargeAmps = rateMaxDecrease
    return newChargeAmps

def updateVehicleChargeRate (activeVehicle, newChargeAmps, currentChargeAmps, ampsToStopCharging) :
    chargeMessage = "No Message Given"
    
    if newChargeAmps <= ampsToStopCharging :
        chargeMessage = "Stopping"
        newChargeAmps = 0
        stopChargingVehicle( activeVehicle )

    elif newChargeAmps > currentChargeAmps :
        chargeMessage = "Increasing"
        setChargeRateForTeslaAPI( activeVehicle, newChargeAmps )

    elif newChargeAmps < currentChargeAmps :
        chargeMessage = "Decreasing"
        setChargeRateForTeslaAPI( activeVehicle, newChargeAmps )

    else :
        chargeMessage = "Charging"
    return chargeMessage

def stopOtherVehicleCharging (vehicleList, activeVehicleName) :
    for vehicle in vehicleList :
        vehicleInfo = getVehicleData( vehicle )
        if not vehicleInfo :
            continue
        
        vehicleChargeInfo = vehicleInfo['charge_state']

        # If the vehicle isn't home continue to the next vehicle
        if vehicleAtHomeCheck( vehicle, vehicleInfo ) == "Away" :
            continue

        # If the vehicle is charging and is not the active vehicle, stop it charging
        if vehicleChargeInfo['charging_state'] == "Charging" and \
           vehicle["display_name"] != activeVehicleName :
            stopChargingVehicle( vehicle )

def vehicleAtHomeCheck (vehicle, vehicleData) :
    if vehicle.available() :
        try :
            # Absolute and rounding logic allows matching GPS with slightly less precision to reduce false Away flags
            if abs( round( ( round( vehicleData['drive_state']['latitude' ], 3 ) - lat ) , 3 ) ) > .001 or \
               abs( round( ( round( vehicleData['drive_state']['longitude'], 3 ) - lon ) , 3 ) ) > .001 :
                location = "Away"
            else :
                location = "Home"
        except:
            location = "Unavailable"
    else :
        location = "Unavailable"
    return location

def getVehicleData (vehicle) :
    try :
        vehicleData = vehicle.get_vehicle_data()
    except :
        print( "GetVehicleData: Tesla failed to update", vehicle["display_name"] )
        return ( False )
    return vehicleData

def nightTime (sleepSeconds, awakeTime) :
    if sleepSeconds > 0 : 
        message = "Nighttime, sleeping until sunrise: " + str( awakeTime )
        printMessageWithTimestamp( message )
        return ( True )
    return ( False )

def noVehicleAvailableToCharge (noVehiclesAvailable, currentChargeAmps, newChargeAmps, activeVehicle, volts, wattsExported) :
    if noVehiclesAvailable :
        currentChargeAmps = 0
        newChargeAmps     = 0
        printStatus( "Nothing to Charge", currentChargeAmps, newChargeAmps, activeVehicle["display_name"], volts, wattsExported )
        return ( True )
    return ( False )

def vehicleAsleepAndExcessSolarGeneration (activeVehicle, wattsExported, minWattsToStartCharging, currentChargeAmps, newChargeAmps, volts) :
    if not activeVehicle.available() and wattsExported > minWattsToStartCharging :
        currentChargeAmps = 0
        newChargeAmps     = 0
        if sendWakeToVehicle( activeVehicle ):
            printStatus( "Waking", currentChargeAmps, newChargeAmps, activeVehicle["display_name"], volts, wattsExported )
            return ( True )
        else:
            # Give the API a chance to find the vehicle
            print( "Wake error. Sleeping 5 minutes and trying again" )
            printStatus( "Waking", currentChargeAmps, newChargeAmps, activeVehicle["display_name"], volts, wattsExported )
            return ( True )
    return ( False )

def vehicleAsleep (activeVehicle, volts, wattsExported) :
    if not activeVehicle.available() :
        currentChargeAmps = 0
        newChargeAmps     = 0
        printStatus( "Sleeping", currentChargeAmps, newChargeAmps, activeVehicle["display_name"], volts, wattsExported )
        return ( True )
    return ( False )

def vehicleIsAwayFromHome (activeVehicle, vehicleData, currentChargeAmps, newChargeAmps, volts, wattsExported) :
    if vehicleAtHomeCheck( activeVehicle, vehicleData ) == "Away" :
        printStatus( "Not Home", currentChargeAmps, newChargeAmps, activeVehicle["display_name"], volts, wattsExported )
        return ( True )
    return ( False )

def vehicleIsCharging (vehicleChargingState, activeVehicle, currentChargeLevel, chargeLimit, chargedata, newChargeAmps, wattsExported, volts, currentChargeAmps, ampsToStopCharging) :
    if vehicleChargingState == "Charging" :
        # If the current battery % or the charge limit % don't match what they were last loop (battery % has increased) print charge stats update
        if  currentChargeLevel != chargedata['battery_level'] or chargeLimit != chargedata['charge_limit_soc'] :

            currentChargeLevel = chargedata['battery_level']
            chargeLimit        = chargedata['charge_limit_soc']
            printChargingUpdate( chargedata, False )

        # Calc new charge rate, send new rate to vehicle, and print status message
        newChargeAmps = calculateNewChargeRate( currentChargeAmps, chargedata, newChargeAmps, wattsExported, volts )
        chargeMessage = updateVehicleChargeRate( activeVehicle, newChargeAmps, currentChargeAmps, ampsToStopCharging )

        printStatus( chargeMessage, currentChargeAmps, newChargeAmps, activeVehicle["display_name"], volts, wattsExported )
        if senseConfigured : 
            # Update Sense with current info (Ha!)
            mutable_plug.data_source.power = newChargeAmps * volts 
        return ( True )
    return ( False )

def excessSolarPowerAndVehicleBatteryIsFull (wattsExported, minWattsToStartCharging, chargedata, activeVehicle, volts) :
    if wattsExported > minWattsToStartCharging and chargedata['battery_level'] >= chargedata['charge_limit_soc'] :
        currentChargeAmps = 0
        newChargeAmps     = 0
        printStatus( "Complete", currentChargeAmps, newChargeAmps, activeVehicle["display_name"], volts, wattsExported )
        return ( True )
    return ( False )

def excessSolarPowerAndVehicleIsDisconnected (wattsExported, minWattsToStartCharging, chargedata) :
    if wattsExported > minWattsToStartCharging and chargedata['charging_state'] == "Disconnected" :
        print( "Please plug in, power at", wattsExported, "watts" )
        return ( True )
    return ( False )

def excessSolarPowerAndVehicleIsAvailableToCharge (wattsExported, minWattsToStartCharging, currentChargeAmps, chargedata, newChargeAmps, volts, activeVehicle) :
    if wattsExported > minWattsToStartCharging :
        newChargeAmps = calculateNewChargeRate( currentChargeAmps, chargedata, newChargeAmps, wattsExported, volts )
        printStatus( "Starting", currentChargeAmps, newChargeAmps, activeVehicle["display_name"], volts, wattsExported )
        startChargingVehicle( activeVehicle, newChargeAmps )
        return ( True )
    return ( False )

def noExcessSolarPowerAndVehicleIsAvailableToCharge (wattsExported, minWattsToStartCharging, currentChargeAmps, newChargeAmps, activeVehicle, volts) :
    if wattsExported <= minWattsToStartCharging :
        printStatus( "Inactive", currentChargeAmps, newChargeAmps, activeVehicle["display_name"], volts, wattsExported )
        return ( True )
    return ( False )

#######################################################################################################################################################################
###############################################################  Start of TesSense Function   #########################################################################
#######################################################################################################################################################################
async def TesSense () :
    # Declare main function variables
    currentChargeAmps        = 0
    newChargeAmps            = 0
    chargeLimit              = 0
    currentChargeLevel       = 0
    previousVehicleTimestamp = 0
    noVehiclesAvailable      = False
    volts                    = int( 240 ) # Set voltage to 240 until we can retrive it from the vehicle
    sun                      = Sun( lat, lon )
    timeZone                 = timezonefinder.TimezoneFinder().certain_timezone_at( lat=lat,lng=lon )
    retry                    = teslapy.Retry( total=3, status_forcelist=( 500, 502, 503, 504 ) )
    
    with teslapy.Tesla( username, retry=retry, timeout=20 ) as tesla :
        vehicleList  = tesla.vehicle_list()
        
        activeVehicle, noVehiclesAvailable = getActiveVehicle( vehicleList )

        # Main loop with night time carve out
        while ( True ):
            # Stop any vehicle from charging other than the active vehicle
            stopOtherVehicleCharging( vehicleList, activeVehicle["display_name"] )
            
            vehicleData = getVehicleData( activeVehicle )
            if not vehicleData :
                # Error: Re-run the loop
                print( "Tesla failed to update, please wait a minute..." )
                await asyncio.sleep( 60 )
                continue

            # Collect new data from Energy Meter
            wattsExported = updatePowerUse()

            # Successfully collected new data from Tesla, updating variables
            chargedata              = vehicleData['charge_state'         ]
            volts                   = chargedata['charger_voltage'       ]
            currentChargeAmps       = chargedata['charger_actual_current']
            vehicleChargingState    = chargedata['charging_state'        ]
            minWattsToStartCharging = ampsToStartCharging * volts
            sleepSeconds, awakeTime = calculateNightSleepSeconds( sun, timeZone )
            # If vehicle is sleeping volts are returned as '2', we handle that here
            if volts < 100 : volts = 240

            # Print climate info and optionally vent windows. Vehicle timestamp is updated every ~12 minutes
            try:
                latestVehicleData = activeVehicle.get_latest_vehicle_data()

                if previousVehicleTimestamp != latestVehicleData['climate_state']['timestamp'] :

                    previousVehicleTimestamp = latestVehicleData['climate_state']['timestamp']
                    printVehicleClimateInfo( latestVehicleData )

                    if ventWindowsIfOverTemperature:
                        ventWindowsIfInteriorAboveSetpoint ( activeVehicle, latestVehicleData )
            except: pass

            # Start of main logic block for the loop
            match ( True ) :
                case _ if nightTime( sleepSeconds, awakeTime ) :
                    await asyncio.sleep( sleepSeconds )
                    activeVehicle, noVehiclesAvailable = getActiveVehicle( vehicleList )

                case _ if noVehicleAvailableToCharge( noVehiclesAvailable, currentChargeAmps, newChargeAmps, activeVehicle, volts, wattsExported ) :
                    await asyncio.sleep( 300 )
                    activeVehicle, noVehiclesAvailable = getActiveVehicle( vehicleList )

                case _ if vehicleAsleepAndExcessSolarGeneration( activeVehicle, wattsExported, minWattsToStartCharging, currentChargeAmps, newChargeAmps, volts ) :
                    await asyncio.sleep( 300 )

                case _ if vehicleAsleep( activeVehicle, volts, wattsExported ) :
                    await asyncio.sleep( 120 )
                    activeVehicle, noVehiclesAvailable = getActiveVehicle( vehicleList )

                ### Vehicle is awake ###

                case _ if vehicleIsDcFastCharging( chargedata ) :
                    await asyncio.sleep( 120 )

                case _ if vehicleIsAwayFromHome( activeVehicle, vehicleData, currentChargeAmps, newChargeAmps, volts, wattsExported ) :
                    await asyncio.sleep( 300 )
                    activeVehicle, noVehiclesAvailable = getActiveVehicle( vehicleList )

                case _ if vehicleIsCharging( vehicleChargingState, activeVehicle, currentChargeLevel, chargeLimit, chargedata, newChargeAmps, wattsExported, volts, currentChargeAmps, ampsToStopCharging ) :
                    await asyncio.sleep( 120 )

                ### There is excess solar but the vehicle is not charging ###

                case _ if excessSolarPowerAndVehicleBatteryIsFull( wattsExported, minWattsToStartCharging, chargedata, activeVehicle, volts ) :
                    await asyncio.sleep( 120 )
                    activeVehicle, noVehiclesAvailable = getActiveVehicle( vehicleList )

                case _ if excessSolarPowerAndVehicleIsDisconnected( wattsExported, minWattsToStartCharging, chargedata ) :
                    await asyncio.sleep( 120 )
                    activeVehicle, noVehiclesAvailable = getActiveVehicle( vehicleList )

                case _ if excessSolarPowerAndVehicleIsAvailableToCharge( wattsExported, minWattsToStartCharging, currentChargeAmps, chargedata, newChargeAmps, volts, activeVehicle ) :
                    await asyncio.sleep( 120 )
                
                case _ if noExcessSolarPowerAndVehicleIsAvailableToCharge( wattsExported, minWattsToStartCharging, currentChargeAmps, newChargeAmps, activeVehicle, volts ) :
                    await asyncio.sleep( 120 )

                case _ :
                    print( "===> No match for switch statement <===" )
                    await asyncio.sleep( 120 )
 
# Made name changes to maintain functionality, otherwise I take no responsibility/credit for this code.  -Jason Dillman
async def CheckTPLink() :                       # Based on github.com/piekstra/tplinkcloud-service
    global output

    def printMessageWithTimestamp(msg) :                         # Wrap a balloon around each output from CheckTPLink()
        print("=" * len(msg))
        print(msg)
        print("-" * len(msg))

    printMessageWithTimestamp("Looking for TPLink smartplugs")
    wattsExported  = 0
    device_manager = TPLinkDeviceManager(username, tpLinkPassword)
    power_manager  = TPLinkDeviceManagerPowerTools(device_manager)
    devices        = await power_manager.get_emeter_devices()
    if not devices : printMessageWithTimestamp("No TPLink (KASA) E-Meter devices found")
    else :
        print("="*72)
        print("Found "+str(len(devices))+" TP-Link E-Meter devices:")
        for i, device in enumerate(devices, 1) :
            print('{:25}'.format(device.device_info.alias), end='' if i % 3 else '\n')
        if i % 3: print()
        print("\nControlled devices:")
        for nameddevice in tpLinkDeviceList :
            device = await power_manager.get_devices_power_usage_realtime(nameddevice)
            unit = await device_manager.find_device(nameddevice)
            if unit.device_info.status :
                print(nameddevice + " watts = " + str(round(device[0].data.power_mw)))
            else : print(nameddevice + " = offline")
        print("-"*72)
        thishour = datetime.datetime.now().time().hour
        while(True) :
            # Sleep until 8 am
            if datetime.datetime.now().time().hour < 8 :
                printMessageWithTimestamp("Nighttime, Sleeping until morning...")
                await asyncio.sleep(60 * (60 - datetime.datetime.now().time().minute))
                await asyncio.sleep(3600 * 8 - (3600 * datetime.datetime.now().time().hour))
                continue
            # Announce on top of the hour to be sure process is still running
            if thishour != datetime.datetime.now().time().hour :
                thishour = datetime.datetime.now().time().hour
                printMessageWithTimestamp(str(thishour-12 if thishour > 12 else thishour) + " o'clock")
            # Build message to display if tpLinkDeviceList devices are using much power
            output = ''
            for nameddevice in tpLinkDeviceList :
                wattsExported = updatePowerUse()
                try:
                    unit = await device_manager.find_device(nameddevice)
                except:
                    printMessageWithTimestamp("Cannot find TPLink device " + nameddevice + " Please wait a minute")
                    await asyncio.sleep(60)
                    continue
                if unit.device_info.status :                    # Check if unit is online
                    try:
                        device = await power_manager.get_devices_power_usage_realtime(nameddevice)
                    except:
                        printMessageWithTimestamp("Cannot find TPLink device status")
                        await asyncio.sleep(60)
                        continue
                    if hasattr(device[0].data, 'voltage_mv') :
                        if device[0].data.voltage_mv > 1000 :
                            factor = 1000                       # If old model data
                        else : factor = 1                       # If new model data
                        watts = device[0].data.power_mw/factor  # Convert to actual watts figure
                                # Power on nameddevice if there is 1000 watts free solar
                        if await unit.is_off() and wattsExported > 1000 :
                            printMessageWithTimestamp("Powering on: " + nameddevice)
                            await unit.power_on()
                                # Power off nameddevice if it is using more than 5 watts and
                                # available power isn't covering at least 2/3rds of it's usage
                        elif watts > 5 and wattsExported < -(watts/3) :
                            printMessageWithTimestamp("Powering off: "+ nameddevice + " because " + str(wattsExported) + " is less than " + str(-(round(watts/3))) + " threshold")
                            await unit.power_off()
                        elif watts > 5 :
                            if output != '' : output = output + "\n"
                            output = output + nameddevice + " = " + str(round(device[0].data.voltage_mv/factor, 2)) + " volts, " + str(round(device[0].data.power_mw/factor,2)) +    " watts, " + str(round(device[0].data.current_ma/factor,2)) +  " amps, "+ str(round(device[0].data.total_wh/factor,2)) +    " 7-day kWhs"

            if output != '' :
                print("=" * 72)
                print(output)
                print("-" * 72)
            await asyncio.sleep(120)

# Much thanks to cbpowell for this SenseLink code:
async def main():
    # Create controller, with NO config
    controller = SenseLink( None )
    
    if emporiaConfigured :
        global vue, emporiaDeviceList, primaryEmporiaDevice, emporiaDeviceGids
        # Retrieve Emporia authentication keys from JSON file
        with open( 'emporia_keys.json' ) as keys :
            data = json.load(keys)

        # Connect to Emporia
        vue = pyemvue.PyEmVue()
        vue.login( 
            id_token           = data['id_token'     ],
            access_token       = data['access_token' ],
            refresh_token      = data['refresh_token'],
            token_storage_file = 'keys.json' )
        
        # Retrieve list of Emporia devices from the Emporia API
        emporiaDeviceList = vue.get_devices()
        emporiaDeviceGids = []
        # Hard coding Emporia device as the first result as this is assumed to be the energy meter
        primaryEmporiaDevice = emporiaDeviceList[0].device_gid
        # Compile a list of Emporia Device global IDs
        for device in emporiaDeviceList:
            if not device.device_gid in emporiaDeviceGids:
                emporiaDeviceGids.append(device.device_gid)        

    if senseConfigured :
        global mutable_plug

        sense.authenticate(username, sensePassword)

        # Create a PlugInstance, setting at least the name for Sense and MAC
        mutable_plug = PlugInstance( "mutable", alias="Tesla", mac="53:75:31:f8:3a:8c" )
        # Create and assign a Mutable Data Source to that plug
        mutable_data_source      = MutableSource( "mutable", None )
        mutable_plug.data_source = mutable_data_source
        
        # Add that plug to the controller
        controller.add_instances( {mutable_plug.identifier: mutable_plug} )

    if tpLinkConfigured :
        # Pass plug to TesSense, where TesSense can update it
        tpLinkTask  = CheckTPLink()
    
    teslaTask = TesSense()

    # Get SenseLink tasks to add these
    taskList = controller.tasks
    # Spawn the TesSense() function as a coroutine
    taskList.add( teslaTask )
    # Spawn the CheckTPLink() function also
    if tpLinkDeviceList : taskList.add( tpLinkTask ) # Not used
    taskList.add( controller.server_start() )

    logging.info( "Starting SenseLink controller" )
    await asyncio.gather( *taskList )


if __name__ == "__main__":
    try:
        asyncio.run( main() )
    except KeyboardInterrupt:
        print( "\n\n Interrupt received, stopping SenseLink\n" )