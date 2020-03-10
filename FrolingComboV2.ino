/**
 *  Modbus RS232-RTU to TCP/IP conversion. 
 *  This program acts as a Modbus Master on the RS232 side, and as a
 *  Modbus slave device on the TCP/IP side.
 *  Two different modbus libraries are used: one for master (ModbusRtu) and another
 *  for slave (Mudbus). MudbusMEK was just a couple name changes because of collisions. 
 *  V1.0 - combined two arduinos into one. This one also does the Froling room temps.
 *  V2.0 - Outside Thermostat  
 */

#include <ModbusRtu.h>
#include <SoftwareSerial.h>
#include <SPI.h>
#include <Ethernet.h>
#include <MudbusMEK.h>
#include <OneWire.h>
#include <DallasTemperature.h>
#include <Wire.h>
#include <avr/wdt.h>                // for auto reboot
#define ONE_WIRE_BUS 5
#define Version 2.0

// data array for modbus network sharing
uint16_t au16data[16];
uint8_t u8state;

/**
 *  Modbus object declaration
 *  u8id : node id = 0 for master, = 1..247 for slave
 *  u8serno : serial port (use 0 for Serial)
 *  u8txenpin : 0 for RS-232 and USB-FTDI 
 *               or any pin number > 1 for RS-485
 */
Modbus master(0); // this is master and RS-232 or USB-FTDI via software serial

/**
 * This is a structure which contains a query to a slave device
 */
modbus_t telegram;
//Instansiate Mudbus class as slave
Mudbus Mb;

unsigned long u32wait;

SoftwareSerial mySerial(6,7);//Create a SoftwareSerial object so that we can use software serial. Search "software serial" on Arduino.cc to find out more details.

// Setup a oneWire instance to communicate with any OneWire devices
OneWire oneWire(ONE_WIRE_BUS);

DallasTemperature sensors(&oneWire);
DeviceAddress Thermometer0 = {0x28, 0xFF, 0x56, 0x5C, 0x54, 0x14, 0x00, 0xB9};  // Heating return
DeviceAddress Thermometer1 = {0x28, 0x9A, 0xFC, 0x2D, 0x07, 0x00, 0x00, 0x70};  // Heating supply
DeviceAddress Thermometer2 = {0x28, 0x6A, 0xD2, 0x5B, 0x06, 0x00, 0x00, 0x52};  // outside temp
DeviceAddress* Thermosensor[3];

void setup(void) {
  Serial.begin(9600);     //hardware serial for debug connection
  mySerial.begin(57600);
  master.begin( &mySerial, 57600 ); // begin the ModBus object. The first parameter is the address of your SoftwareSerial address. Do not forget the "&". 9600 means baud-rate at 9600
  master.setTimeOut( 2000 ); // if there is no answer in 2000 ms, roll over
  u32wait = millis() + 1000;
  u8state = 0; 
   //setup ethernet and start
  uint8_t mac[]   = { 0x90, 0xA2, 0xDA, 0x00, 0x51, 0x24 };   // not the real address
  uint8_t ip[]	= { 192, 168, 1, 54};     // production
//  uint8_t ip[]	= { 192, 168, 10, 152};           // test on desk
  uint8_t gateway[] = { 192,168,1,1};	          // production
//uint8_t gateway[] = { 192,168,10,1};              // test on desk
  uint8_t subnet[]  = { 255, 255, 255, 0};
  Ethernet.begin(mac, ip, gateway, subnet);
  delay(2000);
    //Set some static registers for modbus slave
  for (int i=3; i<12; i++) {
    Mb.R[i] = 0;
  }
  Thermosensor[0]= &Thermometer0;
  Thermosensor[1]= &Thermometer1;
  Thermosensor[2]= &Thermometer2;
  sensors.begin();
  // set the resolution to 10 bit (good enough?)
  for (int i= 0; i < 3; i++) {
    sensors.setResolution(*Thermosensor[i], 10);
  }  
}

void loop() {
  float tempC, tempF;
  Mb.Run();  // check for slave requests
  switch( u8state ) {
  case 0: 
    if (millis() > u32wait) u8state++; // wait state
    break;
  case 1: 
    telegram.u8id = 2; // slave address
    telegram.u8fct = 4; // function code (this one is input registers read)
    telegram.u16RegAdd = 0; // start address in slave
    telegram.u16CoilsNo = 9; // number of elements (coils or registers) to read
    telegram.au16reg = au16data; // pointer to a memory array in the Arduino

    master.query( telegram ); // send query (only once)
    //Add temperature here...
    sensors.requestTemperatures();
    u8state++;
    break;
  case 2:
    master.poll(); // check incoming messages
    if (master.getState() == COM_IDLE) {
      u8state = 3;
      u32wait = millis() + 2000; 
      Mb.R[3] = au16data[0];  // Boiler TEMP!
      Mb.R[4] = au16data[1];  // Flue Gas TEMP!
      Mb.R[5] = au16data[2];  // Board TEMP!
      Mb.R[7] = au16data[7];  // Upper tank TEMP!
      Mb.R[8] = au16data[8];  // Lower Tank TEMP!
      for (int i=0; i<3; i++) {               // *** Set temps in registers, 2=outside 
        tempC = sensors.getTempC(*Thermosensor[i]);
        tempF = DallasTemperature::toFahrenheit(tempC);   //  for the 10ths 
	Mb.R[i+9] = (int16_t) (tempF*10);      // want 10ths also
        #ifdef DEBUG
           Serial.print(i,"temp = ");
           Serial.println(tempF);
        #endif
        }
    }
    break;
    case 3: 
    telegram.u8id = 2; // slave address
    telegram.u8fct = 4; // function code (this one is input registers read)
    telegram.u16RegAdd = 4001; // start address in slave
    telegram.u16CoilsNo = 1; // number of elements (coils or registers) to read
    telegram.au16reg = au16data; // pointer to a memory array in the Arduino

    master.query( telegram ); // send query (only once)
    u8state++;
    break;
  case 4:
    master.poll(); // check incoming messages
    if (master.getState() == COM_IDLE) {
      u8state = 0;
      u32wait = millis() + 2000; 
      Mb.R[6] = au16data[0];  // Boiler state!
    }
    break;
  }
}
