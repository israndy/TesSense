# TesSense
Charge your Tesla with surplus solar generation as detected by your Sense Energy Monitor - 9.6 Release (8/30/22)

TesSense logs into your Sense Energy Monitor and your Tesla account and tracks the amount of surplus 
energy your solar system is generating and asks your Tesla to start or stop charging and adjusts the 
amps used for charging, based on the amount of free solar and updates every two minutes.

Integration with the SenseLink service allows this app to communicate as a TP-Link to the Sense App and 
send the active energy being used for charging by the Tesla so it will be displayed in the Sense App.
This gives extra feedback as to the status of your cars charging and allows you to track the energy

The 9th version introduces TPLink integration allowing you to track and control KASA Smart 
Plugs that can be used for charging or monitoring usage allowing priority control as solar energy becomes 
avaiable. Assign the device names of specific TPLink devices to the Controllist and they will cycle on
and off with the sun

Description:
If you have this app running and plug your Tesla in you can charge using ANY model of EVSE and this 
Python3 script will get information from your car about what capabilities your charge connection has 
and then will track the energy usage in your location, allocating any spare power to charging, up to 
the limits of your wall connector. It plays nicely with the Tesla App allowing you to see the changes 
as they happen and the TesSense app gives feedback about what is happening on it's standard output. 

You will need to edit this app, placing your Username and Password for your Sense Energy Monitor account, 
and your login for your Tesla account in the appropriate locations. The first time this python script 
is run you will be prompted for your password by Tesla and you will receive a confirmation code, paste 
that URL back into the app and you will be logged in securely and you can watch as the app detects your 
surplus solar and uses that to set the charging rate on your car. Before 8 am and after 8 pm or anytime 
there are too many power draws in your location on the free solar the app will ask your Tesla to turn 
off charging. When the surplus solar returns, the charging will start again.

Requires the installation of TeslaPy, and several other libraries document in the code, such as:

python3 -m pip install teslapy
