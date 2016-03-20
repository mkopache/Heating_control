'''
Created on January 16, 2016 V1.0

@author: Mark 
V1.0
The programs receives temperatures and gives commands to the Arduino that controls the 
thermostats in the house. 
see Thermostat controls document for crosswalk of coils to arduino pins to relays to zones
MODBUS master(server) over TCP/IP
This program communicates with Thermostatctrl.ino for the arduino. Version should be the same.
V2.0   -- March 18, 2016
Program was renamed to TarmRoom
Another Arduino was added that is located in the TarmRoom. The Arduino reads temps from the 
injector and the exchanger and makes them available to this program via registers. This version
reads the temps and displays them.  New Associated arduino program is tarmroom.ino
Additionally, temps now read in .1 degree increments by multiply for 10 at arduino and divide 
by 10 at the python end. 
'''

from pymodbus.client.sync import ModbusTcpClient
import os
import sys
import msvcrt                     # windows only
import smtplib                    
from datetime import datetime
info_request = 0
count = 0
max_count = 18 
on_bypass = False
coil_values = [0,0,0,0,0]
email_times = ['08','10','12','14','20']           # emails sent at these hours 
set_point =[ 0,0,63,63,65]
zone_names = [" invalid ", "invalid", "Zone 2, Oak Room temp =   "," Zone 3, Music Room temp = ",
  " Zone 4, 2nd Floor temp =  " ] 
zone_numbers = ['2','3','4']
valid_temps = ['55','56','57','58','59','60','61','62','63','64','65','66','67','68','69','70','71','72','73','74']
current_temp = [0.0,0.0,68.0,68.0,68.0]                 # [0] and [1] not used


def kbfunc():                     # check for input without blocking
   x = msvcrt.kbhit()             # works on Windows only
   if x: 
      ret = ord(msvcrt.getch()) 
   else: 
      ret = 0 
   return ret
def cls():                         # clears the screen
    os.system('cls' if os.name=='nt' else 'clear')

def current_temps():
    for i in range(2,5):
      display_temp = current_temp[i]                          # convert back to 10ths as in 68.8
      if (display_temp < 50.0 or display_temp > 80.0) :       # temps out of range show as 100F
          display_temp = 100
      print zone_names[i], display_temp, "  Set = ", set_point[i]
    print	
	
def command_info():
    global on_bypass
    print
    print " Status : "
    if count % 3 == 0 :                           # set every 3rd cycle
       on_bypass = therm_client.readCoil(1)
    if on_bypass :
       print "     Bypass is ON"
    else :	   
       print "     Bypass is OFF, All Standard zone Thermostats ON"
    for i in range(2,5):                            # individual zone information
      if (count % 3) == 0 :                          # only get arduino coils every 3rd time
          coil_values[i] = therm_client.readCoil(i)
      if coil_values[i] == 0 : 
         c_status = "OFF"
      else :
         c_status = "ON"
      print "     Zone ",i," is ",c_status
    print "\n ",max_count - count, " cycles to Set Point changes"
    if not info_request:
	   print "\n"*2
    print " c to enter command, h for help, or x?",

def syntax_error(line, extra):
    print "syntax error : ",line, ":",extra
    x = raw_input("hit enter to continue")

def print_help():
    print "\n syntax : command (arguments)"
    print " commands are : bypass (on or off)"
    print "              set (zone# || all) (temp)"
    print "   'exit' to end program"
    x=raw_input("hit enter to continue")
	
def check_commands():                 # ensure command valid and execute command
    global on_bypass
    rc = kbfunc();                            # get keyboard input
    if rc == ord('h') :                        # help
        print_help()
    elif rc == ord('x') :                       # exit program
        sys.exit(0)
    elif rc > 0:                                # anything else enter command mode
        line = raw_input("\nenter a command -->")
        parsed = line.split(" ")
        command = parsed[0]
        if command == "exit":
            sys.exit()
        if len(parsed) > 1 :                    # is there the required argument?
           zone = parsed[1]
           if len(parsed) > 2:
              settemp = parsed[2]
        else:
           zone = "No argument"
        if command == "bypass":                  # bypass
           if zone == "on":
              therm_client.writeCoil(1,True)
              on_bypass = True
           elif zone == "off":
              for i in range(2, 5):            # and shut off all temp control relays
                therm_client.writeCoil(i,False) 
              therm_client.writeCoil(1,False)  # and shut off the bypass relays
              on_bypass = False
           else :			   
			  syntax_error(line, "argument should be on or off")
        elif command == "set":                       # set 
           if zone == "all":
		      set_point[2] = int(settemp)         # make this more generic
		      set_point[3] = int(settemp)
		      set_point[4] = int(settemp)
           elif zone in zone_numbers and settemp in valid_temps:         # validate zones # and setpoint value  
               set_point[int(zone)] = int(settemp)
           else:
			  syntax_error(line, "arguments not out of range")
        else:
            syntax_error(line, "not a command")
				
def print_coils():                     # for testing and problem analysis
    for i in range(1,5):
       print "coil ", i, therm_client.readCoil(i)
	   
def check_temps():
    if on_bypass:                                      # check temps vs zones and turn off or on
      for i in range(2, 5):                            # range is +- 2 degree
        if (current_temp[i] > set_point[i]) or (current_temp[i] < 40.0 or current_temp[i] > 80.0) :
           therm_client.writeCoil(i,False)             # turn off thermostat		 
        elif current_temp[i] < set_point[i]  :
           therm_client.writeCoil(i,True)              # turn on thermostat
		   
class MBclient(ModbusTcpClient):
    '''
    Class for MODBUS slave points
    '''
    
    def __init__(self, *args, **kwargs):
        ''' Constructor
        
        default modbus port is 502'''
        #ip address
        self.addr = args[0]
        
        ModbusTcpClient.__init__(self, self.addr)
        
        self.connect()
        
    def readCoil(self, coil):
        '''returns single read of coil value'''
        return self.read_coils(coil, 1).bits[0]
        
    def writeCoil(self, coil, val):
        '''writes value to single coil'''
        val2 = self.readCoil(coil + 1)       # **** this is a work around *******
        val3 = self.readCoil(coil + 2)       # write_coils does multiples coils and write_coil 
        val4 = self.readCoil(coil + 3)       # doesn't work
        self.write_coils(coil, [val, val2, val3, val4])
     #   self.write_coil(coil, val)
		
    def toggleCoil(self, coil):
        '''toggles the current value of a single coil'''
        val = self.read_coils(coil,1).bits[0]
        if type(val) is not bool:
            '''throw exception'''
            print 'communications problem, return read is:', val
        else:
            self.writeCoil(coil, (not val))
 #       if coil == 2:
 #         print " toggleCoil val is ", not val
 #         print " in toggle, after 2 ",therm_client.readCoil(2)
    def readReg(self,reg,val):
		'''reads a register value'''
		return self.read_holding_registers(reg,val,unit=1)
'''
   for sending mail
'''
class Gmail(object):
    def __init__(self, email, password):
        self.email = email
        self.password = password
        self.server = 'smtp.gmail.com'
        self.port = 587
        session = smtplib.SMTP(self.server, self.port)        
        session.ehlo()
        session.starttls()
        session.ehlo
        session.login(self.email, self.password)
        self.session = session

    def send_message(self, subject, body):
        ''' This must be removed '''
        headers = [
            "From: " + self.email,
            "Subject: " + subject,
            "To: " + self.email,
            "MIME-Version: 1.0",
           "Content-Type: text/html"]
        headers = "\r\n".join(headers)
        self.session.sendmail(
            self.email,
            self.email,
            headers + "\r\n\r\n" + body)

class MBserver(object):
    '''
    Class for MODBUS master controllers
    '''
    
    def __init__(self, *args, **kwargs):
        '''
        Constructor
        '''
        #dictionary of Modbus slave classes 
        self.clients = kwargs.pop("clients")
        
#==testing==============================================================        
if __name__ == "__main__": 
    from time import sleep
	
    therm_client = MBclient('192.168.0.51')    # thermisters
    tarm_client = MBclient('192.168.0.52')   # tarmroom thermisters
    
    master = MBserver(
                      clients = {1:therm_client, 2:tarm_client}
                      )
    
    print "Client key names: ", master.clients.keys()
    count = 0

    time = ['0','0','0']
	
while 1:
 #   print "coil 7 value:", therm_client.readCoil(7) # master.clients[1].readCoil(7)
    
 #   master.clients[1].toggleCoil(8)
 #   print "coil 8 toggled:", master.clients[1].readCoil(8)

    response = master.clients[1].readReg(3,2)
    response2 = master.clients[2].readReg(3,2)
    current_temp[2] = response.getRegister(0) / 10.0        # first register in list (reg 3 of client)
    current_temp[3] = response.getRegister(1) / 10.0        # second register in list (reg 4 of client)
    current_temps() 
    #   this is for the water temps from the TARM Room
    inject_temp = response2.getRegister(0)               # registers in tarm list
    exchange_temp = response2.getRegister(1)
    print
    print "Injector temp = ", inject_temp / 10.0
    print "Exchanger temp = ", exchange_temp / 10.0
	#  print "all temps = ", response.registers             # prints entire list
    command_info()                                        # print status and commands
	
    sleep(3)
    check_commands()                                 # process commands, if entered
    count = count + 1
    if count > max_count :                                  # check every minute if any setpoint changes
       check_temps()
       count = 0

    s = datetime.now().strftime('%H:%M:%S')          # get time now
    time = s.split(':')
    msg = zone_names[2] + ' ' + str(current_temp[2])
	             # time[0] is hrs, time[1] is minutes, time[2] is seconds 
    if time[0] in email_times and time[1] == '00' and int(time[2]) < 4 :  # send just once each time
       gm = Gmail('aphouse77@gmail.com', '22java22')
       msg = zone_names[2] + ' ' + str(current_temp[2]) + '     ' + zone_names[3] + ' ' + str(current_temp[3])
       gm.send_message('Temps at home', msg)
 
    cls()                        # clear screen
        
        