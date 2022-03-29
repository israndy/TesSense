# TesSense
Charge your Tesla with surplus solar generation as detected by your Sense Energy Monitor - Seventh Release (3/29/22)

TesSense logs into your Sense Energy Monitor and your Tesla account and tracks the amount of surplus 
energy your solar system is generating and asks your Tesla to start or stop charging and adjusts the 
amps used for charging, based on the amount of free solar and updates every two minutes.

Integration with the SenseLink service allows this app to communicate as a TP-Link to the Sense App and 
send the active energy being used for charging by the Tesla so it will be displayed in the Sense App.
This gives extra feedback as to the status of your cars charging

If you have this app running and plug your Tesla in you can charge using ANY model of EVSE and the 
Python3 script will get information from your car about what capabilities your connection has and then 
will track the energy usage in your location, allocating any spare power to charging, up to the limits 
of your wall connector.

It plays nicely with the Tesla App allowing you to see the changes as they happen and gives feedback 
about what is happening with the TesSense app on it's standard output. With the fifth release of this
app it now supports SenseLink sending the wattage back to the Sense App for logging.

You will need to edit this app, placing your Username and Password for your Sense Energy Monitor account, 
and your login for your Tesla account in the appropriate locations. The first time this python script 
is run you will be prompted for your password by Tesla and you will receive a confirmation code, paste 
that URL back into the app and you will be logged in securely and you can watch as the app detects your 
surplus solar and uses that to set the charging rate on your car. Before sunrise and after the sun starts 
going down or anytime there are too many power draws in your location the app will ask your Tesla to turn 
off charging. When the surplus solar returns, the charging will start again.

Requires the installation of TeslaPy and SenseLink:

python3 -m pip install teslapy

python3 -m pip install senselink
