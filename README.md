# TesSense
Charge your Tesla with surplus solar generation as detected by your Sense Energy Monitor - Second Release (2/2/22)

TeslaSense logs into your Sense Energy Monitor and your Tesla account and tracks the amount of surplus 
energy your solar system is generating and asks your Tesla to start or stop charging and adjusts the 
amps used for charging, based on the amount of free solar and updates every minute.

If you have this app running and plug your Tesla in you can charge using ANY model of EVSE and the 
Python3 script will get information from your car about what capabilities your connection has and then 
will track the energy usage in your location, allocating any spare power to charging, up to the limits 
of your wall connector.

It plays nicely with the Tesla App allowing you to see the changes as they happen and gives feedback 
about what is happening with the app on the standard output.

You will need to edit this app, placing your Username and Password for your Sense Energy Monitor account, 
and your login for your Tesla account in the appropriate locations. The first time this python script 
is run you will be prompted for your password by Tesla and you will receive a confirmation code, paste 
that back into the app and you will be logged in securely and you can watch as the app detects your 
surplus solar and uses that to set the charging rate on your car. Before sunrise and after the sun starts 
going down or anytime there are too many power draws in your location the app will ask your Tesla to turn 
off charging. When the surplus solar returns, the charging will start again.

Requires the installation of TeslaPy and Sense_API:

python3 -m pip install teslapy

python3 -m pip install sense_energy
