'''
It is Python Class for updating the firmware of Arduino boards that use
the ATmegaBOOT_168.c bootloader.
For example Arduino Nano.

The project implements the essential parts that Avrdude uses for the
STK500 protocol for Arduino.
'''

import serial
import serial.tools.list_ports
import time

RESP_STK_OK = 0x10
RESP_STK_IN_SYNC = 0x14

# define various device id's
# manufacturer byte is always the same
# Yep, Atmel is the only manufacturer of AVR micros.  Single source :(
SIG1_ATMEL = 0x1E

# The dictionary key is made up of SIG2 and SIG3
# The value is a list with the name of the CPU and the size of the flash page
AVR_ATMEL_CPUS = {(0x97, 0x03): ["ATmega1280", 128],
                  (0x97, 0x04): ["ATmega1281", 128],
                  (0x97, 0x03): ["ATmega128", 128],
                  (0x97, 0x02): ["ATmega64", 128],
                  (0x95, 0x02): ["ATmega32", 64],
                  (0x94, 0x03): ["ATmega16", 64],
                  (0x93, 0x07): ["ATmega8", 32],
                  (0x93, 0x0A): ["ATmega88", 32],
                  (0x94, 0x06): ["ATmega168", 64],
                  (0x95, 0x0F): ["ATmega328P", 64],
                  (0x95, 0x14): ["ATmega328", 64],
                  (0x94, 0x04): ["ATmega162", 64],
                  (0x94, 0x02): ["ATmega163", 64],
                  (0x94, 0x05): ["ATmega169", 64],
                  (0x93, 0x06): ["ATmega8515", 32],
                  (0x93, 0x08): ["ATmega8535", 32]}


class ArduinoBootloader:
    def __init__(self, *args, **kwargs):
        self.device = None
        self.port = None
        self._hw_version = 0
        self._sw_major = 0
        self._sw_minor = 0
        self._answer = None
        self._cpu_name = ""
        self._cpu_page_size = 0

    @property
    def hw_version(self):
        return str(self._hw_version)

    @property
    def sw_version(self):
        return "{}.{}".format(self._sw_major, self._sw_minor)

    @property
    def cpu_name(self):
        return self._cpu_name

    @property
    def cpu_page_size(self):
        return self._cpu_page_size

    def find_device_port(self):
        ports = serial.tools.list_ports.comports()
        for port in ports:
            if ("VID:PID=1A86:7523" in port.hwid) or ("VID:PID=2341:0043" in port.hwid):
                return port.device
        return ""

    def open(self, port=None, speed=57600):
        """ Find and open the communication port where the Arduino is connected.
        Generate the reset sequence with the DTR / RTS pins.
        Send the sync command to verify that there is a valid bootloader.
        """
        if not port:
            port = self.find_device_port()

        if not port:
            return False
        else:
            self.device = serial.Serial(port, speed, 8, 'N', 1, timeout=1)

        self.port = port

        ''' Clear DTR and RTS to unload the RESET capacitor
            (for example in Arduino) '''
        self.device.dtr = 0  # setDTR(0)
        self.device.rts = 0  # setRTS(0)
        time.sleep(1 / 100)

        ''' Set DTR and RTS back to high '''
        self.device.dtr = 1
        self.device.rts = 1
        time.sleep(1 / 20)

        return self.get_sync()

    def get_sync(self):
        # First send and drain a few times to get rid of line noise
        self.device.timeout = 1 / 5

        for i in range(1, 2):
            self.device.write(b"0 ")
            self.device.read()

        self.device.timeout = 1
        for i in range(1, 3):
            self.device.write(b"0 ")
            val = self.device.read(2)
            if len(val) == 2 and val[0] == RESP_STK_IN_SYNC and val[1] == RESP_STK_OK:
                return True

        return False

    def board_request(self):
        """Get the firmware and hardware version of the bootloader."""
        if not self.cmd_request(b"A\x80 ", answer_len=3):
            return False

        self._hw_version = self._answer[1]

        if not self.cmd_request(b"A\x81 ", answer_len=3):
            return False

        self._sw_major = self._answer[1]

        if not self.cmd_request(b"A\x82 ", answer_len=3):
            return False

        self._sw_minor = self._answer[1]

        return True

    def cpu_signature(self):
        """Get information about the CPU, name and size of the flash memory page"""
        if self.cmd_request(b"u ", answer_len=5):
            if self._answer[1] == SIG1_ATMEL:
                try:
                    list_cpu = AVR_ATMEL_CPUS[(self._answer[2], self._answer[3])]
                    self._cpu_name = list_cpu[0]
                    self._cpu_page_size = list_cpu[1]
                    return True
                except KeyError:
                    self._cpu_name = "SIG2: {:02x} SIG3: {:02x}".format(self._answer[2], self._answer[3])
                    self._cpu_page_size = 0
        return False

    def cmd_request(self, msg, answer_len):
        if self.device:
            self.device.write(msg)
            self._answer = self.device.read(answer_len)

            if len(self._answer) == answer_len and \
                    self._answer[0] == RESP_STK_IN_SYNC and self._answer[answer_len - 1] == RESP_STK_OK:
                return True
        return False

    def write_memory(self, buffer, address, flash=True):
        """Write the buffer to the requested address of the flash memory or eeprom."""
        cmd = bytearray(4)
        cmd[0] = ord('U')
        cmd[1] = (address & 0xFF)
        cmd[2] = ((address >> 8) & 0xFF)
        cmd[3] = ord(' ')

        if self.cmd_request(cmd, answer_len=2):
            buff_len = len(buffer)
            cmd[0] = ord('d')
            cmd[1] = ((buff_len >> 8) & 0xFF)
            cmd[2] = (buff_len & 0xFF)
            cmd[3] = ord('F') if flash else ord('E')

            cmd.extend(buffer)
            cmd.append(ord(' '))

            return self.cmd_request(cmd, answer_len=2)
        return False

    def close(self):
        """Close the serial communication port."""
        if self.device.is_open:
            self.device.close()
            self.device = None
