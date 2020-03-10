// This Arduino sketch reads DS18B20 "1-Wire" digital
// temperature sensors, displays them on a 20x4 display,
// and controls relays for zone controllers.
//   Worse code I've ever written..... needs some significant cleaning!!
// version 1.1 - 12/1/14
// Version 1.2  - 1/7/15   
//      Added basement control for exchanger-bypass via 4 board relays
// Version 1.3  - 1/14/15  changed valve controls to operate 
//              in series(open 1, then close other), not parallel  
// Version 1.3.1  - 1/19/15  change temperature display to one screen
// Version 1.4 -  rework display and include message 
//              when xchg-bypas White valves changing
// Version 1.5 - 2/7/15 - add watchdog 
// Version 1.6 - 2/8/15 - change to automated operation based on temp
//              add status saving across reboots
// Version 1.7 - 3/22/16 - bug fix for exchanger not coming on after reboot
// Version 2.0 - 3/24/16 - added modbus 
// Version 2.1 - 4/3/16  - added coil to start/stop slab pump
// Version 2.2 -         - skipped, no changes
// Version 2.3 -10/25/16 - added coil to command an advance cycle from 3 to 4 (overrides temp)
// this mod setup for TEST (not Prod except thermosensors)
// Version 2.5 - 3/3/17  - fixed problem with exchanger going off and on at loop warmup time
//                            (120 degrees)
// Version 3.0 - 11/25/17 - replaced Tarm with Froling and tanks
// Version 3.1 - 10/10/18 - Added new flow paths in heating house loops. 
//                  1. bypass Takagi for heating via tank only
//                  2. separate loop for preheat
//                  3. moved bypass and heat valves to fix lack of mixing.
// Version 4.0 - Object oriented massive changes based on state machine. 

#include <OneWire.h>
#include <DallasTemperature.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <SPI.h>
#include <Ethernet.h>
#include <avr/wdt.h>                // for auto reboot
#include <EEPROM.h>                 // to save data across reboots
#include <Mudbus.h>

//   TEST or PROD
int xxx;                // this is a dummy(needs to be above testcomp to get around a bug with the #if directive
#define testcomp 1                   ----- comment out for PROD
#define Tarm_Version "V4.0"
boolean test = true;                // change to false for PROD 

// Analog pin 4 to SDA with 10k pullup resistor to 5v
// Analog pin 5 to SCL with 10k pullup resistor to 5v
#if defined(testcomp)
LiquidCrystal_I2C lcd(0x3F,20,4); //set the LCD address to 0x3F for a 20 chars and 4 line display
#else 
LiquidCrystal_I2C lcd(0x27,20,4); //set the LCD address to 0x27 for a 20 chars and 4 line display
#endif
// Data wire for sensors is plugged into Digital pin 7 on the Arduino
#define ONE_WIRE_BUS 7
/*-----( Declare Pin Constants )-----*/
#define Buzzer   1                  // can't be using serial when this being used 
#define Auto_operation_pin 8        // if off, in auto mode, otherwise, just runs slab circulator
#define slab_relay  9               // the pin number

// --------------------------------
/*-----( Declare Constants )-----*/
#define RELAY_ON 1
#define RELAY_OFF 0
#define bypass_ON 0
#define bypass_OFF 1
#define valve_open 0
#define valve_closed 1
#define no_bypass_change 0
#define change_bypass 1
// bypass valves 
#define xchange_open 2
#define propane_express_close 1
#define propane_express_open 0
#define xchange_close 3
#define tank_upper_temp_index 0
//-------------normally heat cycles from 1 thru 7 to 1 thru 7 .....
#define heating_tanks 1               // heating up, bypass off
#define bypass_cycling_on 2 
#define On_tanks 3                  // heating main zones 
#define bypass_cycling_off 4
#define On_propane 5           // heating over
#define bypass_off 8           // dummy
#define heating_slab 9           // dummy
//-----------------------------------------------------------
#define heat_cycle_temp_off 75.0           // prod = 75
#if defined(testcomp)     // testing temperature set points
#define Transition_temp 80.0            // shift between propane and wood
#define Tarm_warmup_temp 79.0            // prod = 80
#define xchange_preheat 82.0               // prod = 120.0
#define temp_bypass_on 87.0                // turn on bypass here prod = 130
#define add_wood       120.0               // prod = 120  
#define temp_bypass_off 80.0               // switch to dump below this prod = 110
#define max_tarm_temp  95.0                // need major dump to slab at temp = 160
#define min_tarm_temp  90.0                // prod = 150 stop heat dump at this
#else               // PROD temperature set points
#define Transition_temp 120.0            // shift between propane and wood
#define Tarm_warmup_temp 80.0            // prod = 80
#define xchange_preheat 120.0               // prod = 120.0
#define temp_bypass_on 130.0                // turn on bypass here prod = 130
#define add_wood       120.0               // prod = 120  
#define temp_bypass_off 110.0               // switch to dump below this prod = 110
#define max_tarm_temp  165.0                // need major dump to slab at temp = 165
#define min_tarm_temp  155.0                 // prod = 150 stop heat dump at this
#endif
//------------------------------------------------------------- 
#if defined(testcomp)
#define WRvalveWorkingTime 8000    // total time for WhiteRogers valves to rotate
#define WRstartDuration  3000       // time to start to ensure it runs to completion
#define TstartDuration  3000
#else
#define WRvalveWorkingTime 40000   // prod times = 45 sec. 
#define WRstartDuration  7000      //  7 sec.
#define TstartDuration 60000       // Taco - 60 sec. 
#endif
#define CONFIG_START 32               // saving status to EEPROM

// Setup a oneWire instance to communicate with any OneWire devices
OneWire oneWire(ONE_WIRE_BUS);

// Pass our oneWire reference to Dallas Temperature. 
DallasTemperature sensors(&oneWire);

// Assign the addresses of your 1-Wire temp sensors.
#define sensor_location1 3
#define sensor_location2 3
#define sensor_count sensor_location1 + sensor_location2
#if defined(testcomp)
// Test thermosensors 
DeviceAddress Thermometer4 = { 0x28, 0xB8, 0x0B, 0x7B, 0x04, 0x00, 0x00, 0x6A };
DeviceAddress Thermometer5 = { 0x28, 0xED, 0x9C, 0x7A, 0x04, 0x00, 0x00, 0xC6 };
#else
// PROD thermosensors
DeviceAddress Thermometer4 = {0x28, 0xFF, 0x7F, 0x6A, 0x54, 0x14, 0x00, 0xF3};
DeviceAddress Thermometer5 = {0x28, 0x79, 0xFE, 0x53, 0x05, 0x00, 0x00, 0x71};
#endif
DeviceAddress* Thermometer[sensor_count];
DeviceAddress Thermometer0 = {0x28, 0x5E, 0x2F, 0x67, 0x05, 0x00, 0x00, 0x97};
DeviceAddress Thermometer1 = { 0x28, 0x9F, 0x73, 0x68, 0x05, 0x00, 0x00, 0x11};
DeviceAddress Thermometer2 = {0x28, 0x4D, 0x8E, 0x68, 0x05, 0x00, 0x00, 0xF1};
DeviceAddress Thermometer3 = {0x28, 0x7A, 0x4A, 0x67, 0x05, 0x00, 0x00, 0x3E};

// device location and function
char* status_msg[] =  {  " ", " Heating Tanks   ", 
      " Bypass going ON ", " On Tank         ",
      " Bypass going OFF", " On Propane      "};

char* row_name[] = {"TankU/M ", "TempF/H ", "HomeRtn "};

const char* title_name = strcat(" Temp in F:  ",Tarm_Version); // just used to print to LCD
int bypass_status = bypass_OFF;                 // default condition at reset
const int relay[] = {
  2, 3, 5, 6, 16, 15};               // pin numbers for bypass relay operation
long relayTimeOn[] = {
  0, 0, 0, 0, 0, 0};              // milli time set on
int relayStatus[] = {
  0, 0, 0, 0, 0, 0};               // on or off 
unsigned long valve_start_time = 0;
boolean bypass_cycling = false,                 // time valve start to move
        switch_change = false,
        first = true,
        slab_on = false, 
        xchange_on = false;
int last_bypass_switch = 0,                    // to determine if switch changed 
    next_valve = 100,
    loop_count = 0,
    valveCount = 1;
int spincount = 0,
    heat_cycle_count = 0,
    title_time = 0,
    title_count = 0,
    warmupCount = 0;
float tank_upper_temp = 0.0,                  //current heat being provided to house
      injection_temp =0.0;
boolean auto_mode = true;
boolean modbus_relay_state[] = {false,false,false,false,false,false,false};

struct StoreStruct {
  // This is for mere detection if they are your settings
  char version[5];
  // just save heat cycle status 
  int heat_cycle_status;
} storage = {
  Tarm_Version,
  // The default values
  On_propane
};
// ============================= class definitions =====================================
class Valve 
{
  public : int openPin, closePin;
           unsigned long timeToChange;       // expected length of time to effect a change
           unsigned long startTime;     // holds when open or close started in milliseconds
  public : void Open()
           {
           };
           void Close()
           {
           };
};
class WhiteValve :Valve
{
  int timeLengthToStart;          // Time to turn on to start the change (on->off, off->on)
  public : WhiteValve(int onNumber, int offNumber, unsigned long change, unsigned long start)   // constructor
       {
         openPin = onNumber;
         closePin = offNumber;
         timeToChange = change;   // in milliseconds
         timeLengthToStart = start;       // in milliseconds 
         startTime = 0;  
       }
       //---------------------------------------------------------------------------------------------
       public : boolean Open()
       {
         if (startTime == 0) 
         {
           startTime = millis();
          // start opening the valve by turning on the relay 
          digitalWrite(openPin, LOW);
          return (false);
         }
         else           // wait for valve to start 
           if (millis() - startTime > timeLengthToStart)             // millis function is "now"
           {
             digitalWrite(openPin, HIGH);                       // turn off the relay
             if (millis() - startTime > timeToChange)           // complete, so reset and allow advance to next step          
             {
               valveCount += 1;
               startTime = 0;
               return(true);
             }
             return(false);
           }
       };
       //---------------------------------------------------------------------------------------------
       public : boolean Close()
       {
         if (startTime == 0) 
         {
           startTime = millis();
          // start opening the valve by turning on the relay 
          digitalWrite(closePin, LOW);
          return(false);
         }
         else           // wait for valve to start 
           if (millis() - startTime > timeLengthToStart)             // millis function is "now"
           {
             digitalWrite(closePin, HIGH);                   // turn off the relay
             if (millis() - startTime > timeToChange)        // complete, so reset and allow advance to next step
             {  
               valveCount += 1;
               startTime = 0;
               return(true);
             }
             return(false); 
           }
       };
};
class TacoValve : Valve
{
   public : TacoValve(int pinNumber, unsigned long change)                 // constructor
       {
         openPin = pinNumber;
         closePin = pinNumber;
         timeToChange = change;
       }
       public : boolean Open()
       {
         digitalWrite(openPin, LOW);
         valveCount += 1;
         return (true);
       }
       public : boolean Close()
       {
         digitalWrite(closePin, HIGH);
         valveCount += 1;
         return (true);
       }
};

//Instansiate Mudbus class
Mudbus Mb;
// Valve definition
WhiteValve toTank(5,6,WRvalveWorkingTime,WRstartDuration) ;            // #1
WhiteValve bypassPropane(2,3,WRvalveWorkingTime,WRstartDuration) ;     // #2
WhiteValve onTankOnly(16,15,WRvalveWorkingTime,WRstartDuration) ;      // #4
TacoValve Preheat(17,TstartDuration);                                  // #3
//=====================Functions Begin ===========================
//===================== Watchdog setup ===========================
// does not use interrupts
void watchdogSetup(void)
{
cli();          // disable all interrupts
wdt_reset();   // reset the WDT timer
/*
 WDTCSR configuration:
 WDIE = 1: Interrupt Enable
 WDE = 1 :Reset Enable
 WDP3 = 1 :For 4000ms Time-out
 WDP2 = 0 :For 4000ms Time-out
 WDP1 = 0 :For 4000ms Time-out
 WDP0 = 0 :For 4000ms Time-out
*/
// Enter Watchdog Configuration mode:
WDTCSR |= (1<<WDCE) | (1<<WDE);  
// Set Watchdog settings:  include (1<<WDIE) at front for interrupt
// Time set for 1 second
WDTCSR =  (1<<WDIE) | (1<<WDE) | (1<<WDP3) | (0<<WDP2) | (0<<WDP1) | (0<<WDP0);
// enable interrupts
sei();
}

//---------------- load heating status config from EEPROM ----------------
// -- only one int stored for status  EEPROM is "Vn.nii" 6 bytes 
void loadConfig() {
  // To make sure there are settings, and they are YOURS!
  // If nothing is found it will use the default settings.
  if (EEPROM.read(CONFIG_START + 1) == Tarm_Version[1] &&
      EEPROM.read(CONFIG_START + 2) == Tarm_Version[2] &&
      EEPROM.read(CONFIG_START + 3) == Tarm_Version[3]) {
      for (unsigned int t=0; t<sizeof(storage); t++)
        *((char*)&storage + t) = EEPROM.read(CONFIG_START + t);  
      }
   else storage.heat_cycle_status = On_propane;   // default
}
void saveConfig() {
  for (unsigned int t=0; t<sizeof(storage); t++)
    EEPROM.write(CONFIG_START + t, *((char*)&storage + t));
}
ISR(WDT_vect)   // Watchdog timer interrupt routing
{
  saveConfig();
}
//=====================  SETUP ===========================
void setup(void)
{
  boolean first;
  Thermometer[2]= &Thermometer3 ;    // return from xchanger
  Thermometer[0]= &Thermometer4 ;    // upper tank temp
  Thermometer[1]= &Thermometer5 ;    // mid tank temp
  Thermometer[3]= &Thermometer2 ;    // from tank to house
  Thermometer[4]= &Thermometer0 ;    // from house to tank
  Thermometer[5]= &Thermometer1 ;    // from slab to tank
  // start serial port
  if (test) Serial.begin(9600);
  // Start up the library
  sensors.begin();
  // set the resolution to 10 bit (good enough?)
  for (int i= 0; i < sensor_count; i++) {
    sensors.setResolution(*Thermometer[i], 10);
  }  
  lcd.init();
  lcd.backlight();

  //-------( Initialize Pins so relays are inactive at reset)----
  //     and set for output
  for(int n = 0; n <=5; n++) {
    digitalWrite(relay[n], HIGH);
    pinMode(relay[n], OUTPUT);
  }
  digitalWrite(slab_relay ,HIGH);    // for slab motor
  pinMode(slab_relay ,OUTPUT);
  //  set bypass on/off 
  pinMode(Auto_operation_pin, INPUT_PULLUP);
  delay(2000);   //wait for all relays to be inactive 
  //loadConfig();  // for watchdog
  title_time = millis();

  watchdogSetup();

//setup ethernet and start
//byte dnsip[] = { 
//  192, 168, 0, 1 }; // dummy, not needed here
  uint8_t mac[]   = { 0x90, 0xA2, 0xDA, 0x00, 0x51, 0x30 };   // not the real address
#if defined(testcomp)
  uint8_t ip[]	= { 192, 168, 10, 152};           // test on desk
  uint8_t gateway[] = { 192,168,10,1};              // test on desk
#else
  uint8_t ip[]	= { 192, 168, 1, 53};     // production
  uint8_t gateway[] = { 192,168,1,1};	          // production
#endif
  uint8_t subnet[]  = { 255, 255, 255, 0};
  Ethernet.begin(mac, ip, gateway, subnet);
  delay(2000);
  Mb.C[1] = false;
  Mb.C[2] = false;
}
// -------------- End Arduino Setup routine  ----------------------
//--------------- Functions section -------------------------------
void spin(){
  char* spinner = {"/^|-"};
  delay(100);
  lcd.setCursor(19,0); 
  lcd.print(spinner[spincount]);
  spincount = (spincount+1) % 4;
}  
// ------------------------------------------------------------------
void beep(unsigned char delayms){
  analogWrite(Buzzer, 200);      // Almost any value can be used except 0 and 255
  // experiment to get the best tone
  delay(delayms);          // wait for a delayms ms
  analogWrite(Buzzer, 0);       // 0 turns it off
  delay(delayms);          // wait for a delayms ms   
}  
//----------------------------------------------------------------------
// gets and prints temps. also adds to the modbus registers
void printTemperature(DeviceAddress deviceAddress,int num)
{
  float tempC = sensors.getTempC(deviceAddress), tempF;
  char *fprt[6] = {"      "};
  if (tempC == -127.00) {
    lcd.print("Error");
    if (test) Serial.print("Error getting temperature");
  } 
  else {
    tempF = DallasTemperature::toFahrenheit(tempC);
    dtostrf(tempF, 5, 1, *fprt);         // set to display nnn.n
    lcd.print(*fprt);
    if (test) 
      {Serial.print("C: ");
       Serial.print(tempC);
       Serial.print(" F: ");
       Serial.print(DallasTemperature::toFahrenheit(tempC)); }
    if (num == tank_upper_temp_index) {        // save tarm temp for later 
       if (tempF > 40.0 && tempF < 190.0)      // must be within range 
          tank_upper_temp = tempF;
    }
    else if (num == 1)
       injection_temp = tempF;
  }
  Mb.R[num+3] = (uint16_t) (tempF * 10);  // temp0 to 5 ==> modbus reg 3 to 8
}   // end Print temperature   
 
//----------------------------------------------------------------
// if switch is on (i.e. grounded) then manual mode is on    
boolean manual_switch_on() {
  if (digitalRead(Auto_operation_pin) == LOW)   // manual mode selected 
     return(true);
  return(false);  
}
//----------------------------------------------------------------
// turn on/off the slab circulator to dump heat    
boolean slab_circ(int relay_function) {
  if (relay_function == RELAY_ON) {
     digitalWrite(slab_relay, LOW);
     return (true);
  }
  else { 
     digitalWrite(slab_relay, HIGH); 
     return (false);
  }
}
//---------------------------------------------------------------
//  operates relays based on coil off(0) or on(1)
void check_coils(int first, int last) {
   //coil 1 for pin 9 for slab circ	
   //coil 2 for pin A1 for exchange circulator
   //Mb.C[8] = digitalRead(8);
   for (int i=first; i<=last; i++) {
      if (Mb.C[i] != modbus_relay_state[i])    // change has occured?
          switch (i) {
             case 1 : { modbus_relay_state[i] = slab_circ(Mb.C[i]);
                        break; }
             case 2 : { modbus_relay_state[i] = false;     // formerly xchanger, not used in 3.0
                    break; }
             case 3 : {  // advance to heating slab as commanded from MB master 
                    if (storage.heat_cycle_status == On_tanks ) {
                      storage.heat_cycle_status = bypass_cycling_off;
                      relayTimeOn[xchange_close] = 0;
                      relayTimeOn[propane_express_open] = 0;
                      modbus_relay_state[i] = 0; 
                      Mb.C[i] = false;           
                      first = true; 
                    }  
                    break; }  
          }  // switch
   }  // for
}

//----------------------------------------------------------------
// write to status area of display - 1st line 
void display_title_line() {
  char* al = "                   ";
  unsigned long now = millis();

  if (manual_switch_on()) {
    al = " On Manual Mode  ";
  } 
  else al = status_msg[storage.heat_cycle_status];  
  
  if (title_time + 2000 > now) {     // swap equally between title 
     lcd.home(); 
     if (title_count++ % 2 == 0)     // and status about every 2 seconds
       lcd.print(title_name);                // standard title
     else 
       lcd.print(al);                // status info
     title_time = now;
  } 
  else title_time += 4000;  
}
//----------------------------------------------------------------
// write temperatures to display and to modbus registers 
void display_temps() {
  int j = 0;
  for (int i= 0; i < 3 ; i++)                   // display temperatures
  {
    lcd.setCursor(0, i+1);                      // set row
    lcd.print(row_name[i]);                     // print row name
    if (test) Serial.print("printing temps\n");
    printTemperature(*Thermometer[j],j);        // first column
    lcd.setCursor(13, i + 1);                   // print separator
    if (i<2) lcd.print("->"); 
    else lcd.print("<>");
    lcd.setCursor(15, i + 1);                   // second column
    j += 1;
    printTemperature(*Thermometer[j],j);
    j += 1; 
    spin();
  }
}
// ------------ end Functions ------------------------------------
//------------- Main Loop  ----------------------------------------
void loop(void)
{ 
  int j = 0;
  
  if (test) { 
    Serial.print("\nNew Loop ");
    Serial.print(loop_count++);
    Serial.println();
  }
  wdt_reset();              // restart reboot function to beginning
  sensors.requestTemperatures();
  display_title_line();     // print title and status information
  spin();
  Mb.Run();
  display_temps();          // show on 4x20 screen
  Mb.R[9] = (uint16_t) (storage.heat_cycle_status); 
  check_coils(1,3);     // turn on / off slab (1) or xchanger(2) or heat cycle advance (3)
  switch (storage.heat_cycle_status) {
     case On_propane : {                        // tank temp below minimum or 
                                             // or waiting for tanks to heat via froling 
          if (tank_upper_temp > Transition_temp + 1.0)     // open valves to use tank hot water
            storage.heat_cycle_status = heating_tanks;
          break;
     }
     case heating_tanks : {    // check for next temp setpoint and when ready (#1)
                            // set bypass_cycling_on
          storage.heat_cycle_status = bypass_cycling_on;    // bypass for now. may use later 
          valveCount = 1;         
          break;
     }
     case bypass_cycling_on : {               // cycles through here based on timers  
           if (valveCount == 1)                // open path to tank
             toTank.Open(); 
           else if (valveCount == 2)         // open hot water outlet from tanks
             onTankOnly.Open();
           else if (valveCount == 3)
           {
             bypassPropane.Close();                     // complete
             if (valveCount > 3) 
             {
               storage.heat_cycle_status = On_tanks;
               saveConfig();               // in case of reboot
             }
           }          
           break;
     }
     case On_tanks : {                 	 // stays using tank until upper temp drops below minimum
            if (tank_upper_temp < Transition_temp - 3.0) {
              storage.heat_cycle_status = bypass_cycling_off;
              valveCount = 1;             
           }    
           break;
     }
     case bypass_cycling_off : {
           if (valveCount == 1)                // open path to tank
             bypassPropane.Open(); 
           else if (valveCount == 2)         // open hot water outlet from tanks
             toTank.Close();
           else if (valveCount == 3)
           {
             onTankOnly.Close();                     // complete
             if (valveCount > 3)
             {
               storage.heat_cycle_status = On_propane;
               saveConfig();               // in case of reboot
             }
           }          
           break;
     }
  }
  //
  delay(100);
  
  spin();
  // beep (50); this one works with RadioShack buzzer
  //tone (Buzzer, 400, 2000);
  //noTone (Buzzer);
}
/* pins used
 0,1 serial
 2,3,5,6,15,16,17 valve relays
 7 Dallas Onewire
 8 
 9 slab circulator relay
 4,10,11,12,13 - Ethernet 
 14 
*/ 
