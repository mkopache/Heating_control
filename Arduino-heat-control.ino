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
// this mod setup for Test (not Prod except thermosensors)

#include <OneWire.h>
#include <DallasTemperature.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <SPI.h>
#include <Ethernet.h>
#include <avr/wdt.h>
#include <EEPROM.h>

// Analog pin 4 to SDA with 10k pullup resistor to 5v
// Analog pin 5 to SCL with 10k pullup resistor to 5v
LiquidCrystal_I2C lcd(0x27,20,4); //set the LCD address to 0x27 for a 20 chars and 4 line display

// Data wire for sensors is plugged into Digital pin 7 on the Arduino
#define ONE_WIRE_BUS 7
/*-----( Declare Pin Constants )-----*/
#define Buzzer   1                  // can't be using serial when this being used 
#define Auto_operation_pin 8        // if off, in auto mode, otherwise, just runs slab circulator
#define slab_relay  9               // the pin number
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
//-------------normally heat cycles from 1 thru 7 to 1 thru 7 .....
#define heat_started 1               // heating up, bypass off
#define bypass_cycling_on 2 
#define bypass_on 3                  // heating main zones 
#define bypass_cycling_off 4
#define bypass_off 5                 // temps declining
#define heating_slab 6               // heating the basement slab
#define heat_cycle_ended 7           // heating over
//-----------------------------------------------------------
#define heat_cycle_temp_on 79.0                 // prod = 80
#define temp_bypass_on 87.0                    // turn on bypass here prod = 130
#define add_wood       120.0                    // prod = 120  
#define temp_bypass_off 80.0                    // switch to dump below this prod = 110
#define heat_cycle_temp_off 75.0                // prod = 75
#define max_tarm_temp  95.0                    // need major dump to slab at temp = 160
#define min_tarm_temp  90.0                    // prod = 140 stop heat dump at thi
// change for testing and version control 
#define valve_working_time 10000   // 45 sec. prevent off and on quick switching by ignoring until done
#define duration  5000;   //10 sec. sets relay time ON. Will be set by other info/variables in future
#define Tarm_Version "V1.6"
#define CONFIG_START 32               // saving status to EEPROM
boolean test = true;

// Setup a oneWire instance to communicate with any OneWire devices
OneWire oneWire(ONE_WIRE_BUS);

// Pass our oneWire reference to Dallas Temperature. 
DallasTemperature sensors(&oneWire);

// Assign the addresses of your 1-Wire temp sensors.
#define sensor_location1 3
#define sensor_location2 3
#define sensor_count sensor_location1 + sensor_location2
// Test thermosensors 
DeviceAddress Thermometer0 = { 0x28, 0xB8, 0x0B, 0x7B, 0x04, 0x00, 0x00, 0x6A };
DeviceAddress Thermometer5 = { 0x28, 0xED, 0x9C, 0x7A, 0x04, 0x00, 0x00, 0xC6 };
// end test
DeviceAddress* Thermometer[sensor_count];
//DeviceAddress Thermometer0 = {0x28, 0xXX, 0x2F, 0x67, 0x05, 0x00, 0x00, 0x97};
DeviceAddress Thermometer1 = { 0x28, 0xXX, 0x73, 0x68, 0x05, 0x00, 0x00, 0x11};
DeviceAddress Thermometer2 = {0x28, 0xXX, 0x8E, 0x68, 0x05, 0x00, 0x00, 0xF1};
DeviceAddress Thermometer3 = {0x28, 0xXX, 0x4A, 0x67, 0x05, 0x00, 0x00, 0x3E};
DeviceAddress Thermometer4 = {0x28, 0xXX, 0x7F, 0x6A, 0x54, 0x14, 0x00, 0xF3};
//DeviceAddress Thermometer5 = {0x28, 0xXX, 0xFE, 0x53, 0x05, 0x00, 0x00, 0x71};
// device location and function
// preV1.4 char* sensor_name[] = {  "Basement_xchg_cold ", "Basement_slab_cold ", 
//      "Basement_xchg_hot  ", "TarmRoom_prmx_cold ",
//      "TarmRoom_psmx_warm ", "TarmRoom_all__hot  "};
char* row_name[] = {"TarmRtn ", "Xchange ", "HomeRtn "};

String sl; // just used to print to LCD
int bypass_status = bypass_OFF;                 // default condition at reset
const int relay[] = {
  2, 3, 5, 6};               // pin numbers for bypass relay operation
long relayTimeOn[] = {
  0, 0, 0, 0};              // milli time set on
int relayStatus[] = {
  0, 0, 0, 0};               // on or off 
unsigned long valve_start_time = 0;
boolean bypass_cycling = false,                 // time valve start to move
        switch_change = false,
        first = true,
        slab_on = false;
int last_bypass_switch = 0 ;                    // to determine if switch changed 
int next_valve = 100;
int spincount = 0,
    heat_cycle_count = 0,
    title_time = 0,
    title_count = 0;
float tarm_heat;                   //current heat being provided to house
boolean auto_mode = true;
struct StoreStruct {
  // This is for mere detection if they are your settings
  char version[5];
  // just save heat cycle status 
  int heat_cycle_status;
} storage = {
  Tarm_Version,
  // The default values
  heat_cycle_ended
};


//Ethernet.begin(mac, ip, dnsip,gatewayip);
// the media access control (ethernet hardware) address for the shield:
byte mac[] = { 
  0x40, 0x00, 0xBE, 0xEF, 0xFE, 0xED };  
//the IP address for the shield: not using DHCP
byte ip[] = { 
  192, 168, 0, 50 };
byte dnsip[] = { 
  192, 168, 0, 1 }; // dummy
byte gatewayip[] = { 
  192, 168, 0, 1 };
//=====================Functions Begin ===========================
//===================== Watchdog setup =======================
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
   else storage.heat_cycle_status = heat_cycle_ended;   // default
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
  Thermometer[0]= &Thermometer3 ;    // return from xchanger
  Thermometer[1]= &Thermometer4 ;    // post injection pump
  Thermometer[2]= &Thermometer5 ;    // tarm temperature to xchanger
  Thermometer[3]= &Thermometer2 ;    // from xchanger to house
  Thermometer[4]= &Thermometer0 ;    // from house to xchanger
  Thermometer[5]= &Thermometer1 ;    // from slab to xchanger
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
  for(int n = 0; n <=3; n++) {
    digitalWrite(relay[n], HIGH);
    pinMode(relay[n], OUTPUT);
  }
  digitalWrite(slab_relay ,HIGH);
  pinMode(slab_relay ,OUTPUT);
  //  set bypass on/off 
  pinMode(Auto_operation_pin, INPUT_PULLUP);
  delay(2000); //Check that all relays are inactive at Reset
  loadConfig();
  title_time = millis();
  sl = String(" Temp in F:  ");    // always print this
  sl = sl + Tarm_Version;
  // Buzzer
  //   pinMode(6, OUTPUT);
  watchdogSetup();
  if (storage.heat_cycle_status == heating_slab)   // reboot happened curing slab heating
     slab_on = slab_circ(RELAY_ON);    // turn on circulator
}
// -------------- End Arduino Setup routine  ----------------------
//--------------- Functions section -------------------------------
void spin(){
  char* spinner = {"/^|-"};
  delay(200);
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
void printTemperature(DeviceAddress deviceAddress,int num)
{
  float tempC = sensors.getTempC(deviceAddress), tempF;
  char *fprt[5] = {
    "     "  };
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
    if (num == 2)        // save tarm temp for later 
       tarm_heat = tempF;
  }
}   // end Print temperature   

//----------------------------------------------------------------
// Bypass valves are operated independently to make sure enough amps 
//       valves pairs are 2 then 1, and 0 then 3; open first, then close
boolean turn_bypass(int valve, boolean first) {
  unsigned long z = duration;
  unsigned long now = millis();
  if (relayTimeOn[valve] == 0) {             // starting opening 
    if (test) Serial.println("starting turn-bypass valve = "+String(valve));
    relayUpdate(HIGH, valve);
    relayTimeOn[valve] = now + valve_working_time;
  }                    // wait for valve to finish
  else { 
    relayUpdate(LOW,valve);
    if (now > relayTimeOn[valve])         // operation is complete
       if (first)
          return(false);
       else {
          bypass_cycling = true; 
          return(true);
       }
  }    
  return (first);    // still awaiting valve operation timer completion
}
 
//----------------------------------------------------------------
// tests and sets relay timers for xchange valves only, and turns 
//              on/off relays based on duration
void relayUpdate(int Condition, int n ) {

  if(Condition == HIGH && relayStatus[n] == 0){
    if (test) Serial.println("turning relay on "+String(relay[n]));
    digitalWrite(relay[n], LOW);    //changes relay status
    relayStatus[n] = 1;
  }
  else{                                // turn relay off if on long enough to operate
    unsigned long z = duration;
    unsigned long now = millis();
    if(now - (relayTimeOn[n] - valve_working_time) > z) {
      if (test)  { Serial.println("turning relay off "+String(relay[n]));
             Serial.println("now is "+String(now));
             Serial.println("relayTimeOn is "+String(relayTimeOn[n])); }
      digitalWrite(relay[n], HIGH);
      relayStatus[n] = 0;
      relayTimeOn[n] = 0;
    }
  }
}
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
//----------------------------------------------------------------
// wait for valves to work and make sure system doesn't reset
void valve_wait_with_spin() {
   int delay_count = valve_working_time / duration;
   int wait_on = duration;    // this version has some problems with #define
   wait_on = wait_on / 500;
   for (int j = 0; j < delay_count; j++) {
     for (int i = 0; i < wait_on; i++) {  // wait for valve to start
       delay(500);
       wdt_reset();     // and make sure system doesnt reboot
       if (test) Serial.println("waiting"+i);
     }
     spin();
   }
}
//----------------------------------------------------------------
// write to status area of display - 1st line 
void display_title_line() {
  String al;
  unsigned long now = millis();

  lcd.setCursor(0, 0);
  if (manual_switch_on()) {
    al = String(" On Manual Mode  ");
  }
  else  
  switch (storage.heat_cycle_status) {
     case heat_started : 
        al = String(" Heating Up Tarm ");
        break;
     case bypass_cycling_on :
        al = String(" Bypass going ON ");
        break;     
     case bypass_on :
        al = String(" Heating house   ");
        break; 
     case bypass_cycling_off : 
        al = String(" Bypass going OFF");
        break;
     case heating_slab :
        al = String(" Heating Slab    "); 
        break;
     default :
        al = String(" Awaiting firing " );  
        //title_time = now; 
        break;
  }
  if (title_time + 2000 > now) {     // swap equally between title 
     if (title_count++ % 2 == 0)     // and status about every 2 seconds
       lcd.print(sl);                // standard title
     else 
       lcd.print(al);                // status info
     title_time = now;
  }
  else title_time += 4000;
}
//----------------------------------------------------------------
// write temperatures to display 
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
  
  if (test) Serial.print("Getting temperatures...\n\r");
  wdt_reset();              // restart reboot function to beginning
  sensors.requestTemperatures();
  display_title_line();     // print title and status information
  spin();
  display_temps();
  // *** how to jump to other statuses and not go in sequence. 
  //  likely jumps -- heating up to heating slab 
  switch (storage.heat_cycle_status) {
     case heat_cycle_ended :
          if (manual_switch_on())
             slab_on = slab_circ(RELAY_ON); 
          else {
               if (slab_on)     // went from manual to auto mode
                  slab_on = slab_circ(RELAY_OFF);
               if (tarm_heat > heat_cycle_temp_on) 
                 heat_cycle_count += 1;
               if (heat_cycle_count > 5) {    // 5 over  temp
                 storage.heat_cycle_status = heat_started;
                 heat_cycle_count = 0;
              }
          }
          // check on manual mode here and heat_started.
          break;
     case heat_started :    // check for next temp setpoint and when ready
                            // set bypass_cycling_on
          if (manual_switch_on())
             slab_on = slab_circ(RELAY_ON); 
          else {
               if (slab_on)     // went from manual to auto mode
                 slab_on = slab_circ(RELAY_OFF);
               if (tarm_heat > temp_bypass_on) {
                  storage.heat_cycle_status = bypass_cycling_on;
                  relayTimeOn[xchange_open] = 0;
                  relayTimeOn[propane_express_close] = 0;              
                  first = true; 
                }
                else if (tarm_heat < heat_cycle_temp_off)  // reset 
                     storage.heat_cycle_status = heat_cycle_ended;  
           } 
           break;
     case bypass_cycling_on :               
           if (first)                       // open exchanger
             first = turn_bypass(xchange_open,first);
           else {                           // open complete, close propane express
             first = turn_bypass(propane_express_close,first);
             if (first)                     // complete
               storage.heat_cycle_status = bypass_on;
               saveConfig();               // in case of reboot
           }          
           break;
     case bypass_on :                      // figure out warning about heat drop
             // either ran out of wood OR likely all circulators off and tarm heating up
           if (tarm_heat < temp_bypass_off) {
              storage.heat_cycle_status = bypass_cycling_off;
              relayTimeOn[xchange_close] = 0;
              relayTimeOn[propane_express_open] = 0;              
              first = true; 
           }
           else if (tarm_heat >= max_tarm_temp)  // dump heat to slab
                   slab_on = slab_circ(RELAY_ON);   // turn pump on 
                else if (slab_on && tarm_heat < min_tarm_temp)
                    slab_on = slab_circ(RELAY_OFF); // turn pump off     
           break;
     case bypass_cycling_off :
           if (first)                       // open propane express
             first = turn_bypass(propane_express_open,first);
           else {                           // open complete, close xchanger 
             first = turn_bypass(xchange_close,first);
             if (first)
               storage.heat_cycle_status = bypass_off;
           }          
           break;
     case bypass_off :    // now dump heat, must turn on slab circulator 
           slab_on = slab_circ(RELAY_ON);    // turn on circulator
           storage.heat_cycle_status = heating_slab;
           saveConfig(); 
           // On reboot, circulator is started again in setup routine - DONE
           break;
     case heating_slab :  // too cold even for slab, turn off slab circulator
           if (tarm_heat < heat_cycle_temp_off) {
              slab_on = slab_circ(RELAY_OFF); // turn off circulator 
              storage.heat_cycle_status = heat_cycle_ended;
           }
           break;
  }
  //
  delay(200);
  spin();
  // beep (50); this one works with RadioShack buzzer
  //tone (Buzzer, 400, 2000);
  //noTone (Buzzer);
}
/* pins used
 0,1 serial
 2,3,5,6 exchanger relays
 7 Dallas Onewire
 8 manual or auto mode
 9 slab circulator relay
 4,10,11,12,13 - Ethernet 
*/ 
