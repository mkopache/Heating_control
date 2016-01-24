/* Thermister and thermostate bypass control program using 
   Mudbus TCP/IP modbus interface in conjuntion with python under Windows 
   program
*/

#include <SPI.h>
#include <Ethernet.h>
#include <Mudbus.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Wire.h>
#include <avr/wdt.h>                // for auto reboot
#define ONE_WIRE_BUS 15
//#define DEBUG
#define Z2coil 2           // command coils for zones
#define Z3coil 3           // for Arduino override
#define Z4coil 4
#define Thermstatsoffon 1
#define Z2relay 7          // pins that control relay  zones 
#define Z3relay 8           //   using Arduino thermisters 
#define Z4relay 9
#define thermrelay2 2       // control pins for relays
#define thermrelay3 3       //    to bypass thermostats
#define thermrelay4 5
// Setup a oneWire instance to communicate with any OneWire devices
OneWire oneWire(ONE_WIRE_BUS);

// Pass our oneWire reference to Dallas Temperature. 
// Data wire for sensors is plugged into Digital pin 7 on the Arduino

DallasTemperature sensors(&oneWire);
DeviceAddress Thermometer0 = {0x28, 0xFF, 0x80, 0x55, 0x54, 0x14, 0x00, 0xE8};
DeviceAddress Thermometer1 = {0x28, 0xC6, 0xDD, 0x2D, 0x07, 0x00, 0x00, 0x16};
DeviceAddress Thermometer2 = {0x28, 0xFF, 0x80, 0x55, 0x54, 0x14, 0x00, 0xE8};
DeviceAddress* Thermosensor[3];
//Instansiate Mudbus class
Mudbus Mb;
int i;
boolean current_state[5];
int relay[5];

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


void setup(void){
 //setup ethernet and start
  uint8_t mac[]   = { 0x90, 0xA2, 0xDA, 0x00, 0x51, 0x16 };   // not the real address
  uint8_t ip[]	= { 192, 168, 10, 51};
  uint8_t gateway[] = { 192,168,10,1};	
  uint8_t subnet[]  = { 255, 255, 255, 0};
  Ethernet.begin(mac, ip, gateway, subnet);
  Thermosensor[0]= &Thermometer0;
  Thermosensor[1]= &Thermometer1;
  Thermosensor[2]= &Thermometer2;   
  sensors.begin();
  // set the resolution to 10 bit (good enough?)
  for (int i= 0; i < 3; i++) {
    sensors.setResolution(*Thermosensor[i], 10);
  }  
  
  //Avoid pins 4,10,11,12,13 when using ethernet shield
  delay(5000); //Time to open the terminal
  relay[2] = Z2relay;
  relay[3] = Z3relay;
  relay[4] = Z4relay;
  #ifdef DEBUG
    Serial.begin(9600);
  #endif	
   pinMode(2, OUTPUT);
   digitalWrite(2,HIGH);
   pinMode(3, OUTPUT);
   digitalWrite(3,HIGH);
   for (i = 5; i<9; i++) {
     pinMode(i, OUTPUT);
     digitalWrite(i,HIGH);
   }
   for (i=1; i<5; i++) {
      current_state[i] = false;
      Mb.C[i] = 0; 
   }
  //Set some static registers and coils
  Mb.R[1] = 4294967295;
  Mb.R[2] = 1500;		//millivolts i.e. AIN
  watchdogSetup();
}

void loop(void){
        float tempC, tempF;
        //Run MODBUS service
        wdt_reset();              // restart reboot function to beginning
	Mb.Run();
  
	//pin 7 to coil 7
	//Mb.C[7] = digitalRead(7);	
	//coil 8 write to pin 8
	//digitalWrite(8, Mb.C[8]);

	#ifdef DEBUG
	  if (Serial.available() > 0) {
        	Serial.print("C8 = ");
	        Serial.println(Mb.C[8]);
	        Serial.print("C7 = ");
	        Serial.println(Mb.C[7]);
                while(Serial.available()>0){Serial.read();}
          }
	#endif
	
	//Add temperature here...
        sensors.requestTemperatures();
        for (i=0; i<2; i++) {                        // *** only sets first 2 zones 
           tempC = sensors.getTempC(*Thermosensor[i]);
           tempF = DallasTemperature::toFahrenheit(tempC);
	   Mb.R[i+3] = (uint16_t) tempF;
           #ifdef DEBUG
              Serial.print(i,"temp = ");
              Serial.println(tempF);
           #endif
        }

        if (Mb.C[1] != current_state[1])         // change?
          if (Mb.C[1] > 0) {                     // Thermostat bypass on/off
            digitalWrite(2, LOW);                // turn on bypass relays 
            digitalWrite(3, LOW);              
            digitalWrite(5, LOW);              
            current_state[1] = true;
          }
          else {
            digitalWrite(2, HIGH);                // turn off bypass relays 
            digitalWrite(3, HIGH);              
            digitalWrite(5, HIGH);              
            current_state[1] = false;
          }
          for (i=2; i<5; i++) {
            if (Mb.C[i] != current_state[i])         // change?
              if (Mb.C[i] > 0) {                     // 1 is turn on
                digitalWrite(relay[i], LOW);          // turn on relay 
                current_state[i] = true;
              }
              else { 
                digitalWrite(relay[i], HIGH);              // turn off relay 
                current_state[i] = false;
              }
          }
}

