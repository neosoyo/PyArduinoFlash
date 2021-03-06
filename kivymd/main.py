'''
Application in Kivy to show the operation of updating the firmware of an Arduino board in python.
'''
from kivy.lang import Builder
from kivy.clock import Clock
from kivymd.app import MDApp

import threading
from queue import Queue

from intelhex import IntelHex
from intelhex import AddressOverlapError
from arduinobootloader import ArduinoBootloader


KV = '''
Screen:
    MDBoxLayout:
        orientation:"vertical"
        padding:10
        spacing:10
            
        MDBoxLayout:
            orientation:"horizontal"
            padding:10
            spacing:10
            
            MDLabel:
                text:"Bootloader version"
            MDLabel:
                id:sw_version
                text:"--"
                
        MDBoxLayout:
            orientation:"horizontal"
            padding:10
            spacing:10
            
            MDLabel:
                text:"Bootloader hardware version"
            MDLabel:
                id:hw_version
                text:"--"
        
        MDBoxLayout:
            orientation:"horizontal"
            padding:10
            spacing:10
            
            MDLabel:
                text:"Bootloader name"
            MDLabel:
                id:prg_name
                text:"--"
       
        MDBoxLayout:
            orientation:"horizontal"
            padding:10
            spacing:10
            
            MDLabel:
                text:"CPU Name"
            MDLabel:
                id:cpu_version
                text:"--"
                         
        MDBoxLayout:
            orientation:"horizontal"
            padding:10
            spacing:10
            
            MDLabel:
                text:"File information"
            MDLabel:
                id:file_info
                text:"--"
        MDBoxLayout:
            orientation:"horizontal"
            padding:10
            spacing:10
            
            MDTextField
                id:file_name
                hint_text: "Intel HEX file format"
                helper_text: "Please enter the file and path of the Arduino firmware"
                helper_text_mode: "on_focus"
                text:"test.hex"
        
        MDBoxLayout:
            orientation: "horizontal"
            ScrollView:
                MDList:
                                     
                    ThreeLineAvatarListItem:
                        on_release: app.on_sel_programmer(115200, "Stk500v1")  
                        text: "Protocol arduino or STK500V1"
                        secondary_text: "for boards up to 128 Kbytes"
                        tertiary_text: "example Nano or Uno - baudarate 115200"
                        ImageLeftWidget:
                            source: "images/arduino-nano.png"
                    
                    ThreeLineAvatarListItem:
                        on_release: app.on_sel_programmer(57600, "Stk500v1") 
                        text: "Protocol arduino or STK500V1 - older"
                        secondary_text: "for boards up to 128 Kbytes"
                        tertiary_text: "example Nano or Uno - baudarate 57600"  
                        ImageLeftWidget:
                            source: "images/arduino-uno.png" 
        
                    ThreeLineAvatarListItem:
                        on_release: app.on_sel_programmer(115200, "Stk500v2") 
                        text: "Protocol wiring or STK500V2"
                        secondary_text: "for boards with more than 128 Kbytes"
                        tertiary_text: "example Mega - baudarate 115200"
                        ImageLeftWidget:
                            source: "images/arduino-mega-2560-original.png"
                                                                    
        MDBoxLayout:
            padding: "10dp"
            orientation: "horizontal"
            MDProgressBar:
                id: progress
                value: 0
                min: 0
                max: 1
        
        MDBoxLayout:
            padding: "10dp"
            orientation: "horizontal"    
            MDLabel:
                id: status
                text:"--"
                       
        MDRectangleFlatButton:
            text:"Flash"
            pos_hint:{'center_x': .5, 'center_y': .5}
            on_release:app.on_flash()
'''


class MainApp(MDApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.ih = IntelHex()
        self.ab = ArduinoBootloader()
        self.working_thread = None
        self.progress_queue = Queue(100)
        self.protocol = "Stk500v1"
        self.baudrate = 115200

    def build(self):
        return Builder.load_string(KV)

    def on_sel_programmer(self, baudrate, protocol):
        self.baudrate = baudrate
        self.protocol = protocol

    def on_flash(self):
        del self.ih

        try:
            self.ih = IntelHex()
            self.ih.fromfile(self.root.ids.file_name.text, format='hex')
        except FileNotFoundError:
            self.root.ids.file_info.text = "File not found"
            return
        except AddressOverlapError:
            self.root.ids.file_info.text = "File with address overlapped"
            return

        self.root.ids.file_info.text = "start address: {} size: {} bytes".format(self.ih.minaddr(), self.ih.maxaddr())

        """The firmware update is done in a worker thread because the main 
           thread in Kivy is in charge of updating the widgets."""
        self.root.ids.progress.value = 0
        self.working_thread = threading.Thread(target=self.thread_flash)
        self.working_thread.start()

    def thread_flash(self):
        """If the communication with the bootloader through the serial port could be
           established, obtains the information of the processor and the bootloader."""
        res_val = False

        """First you have to select the communication protocol used by the bootloader of 
        the Arduino board. The Stk500V1 is the one used by the Nano or Uno, and depending 
        on the Old or New version, the communication speed varies, for the new one you 
        have to use 115200 and for the old 57600.
        
        The communication protocol for boards based on Mega 2560 is Stk500v2 at 115200."""
        prg = self.ab.select_programmer(self.protocol)

        if prg.open(speed=self.baudrate):
            if prg.board_request():
                self.progress_queue.put(["board_request"])
                Clock.schedule_once(self.progress_callback, 1 / 1000)

            if prg.cpu_signature():
                self.progress_queue.put(["cpu_signature"])
                Clock.schedule_once(self.progress_callback, 1 / 1000)

            """Iterate the firmware file into chunks of the page size in bytes, and 
               use the write flash command to update the cpu."""
            for address in range(0, self.ih.maxaddr(), self.ab.cpu_page_size):
                buffer = self.ih.tobinarray(start=address, size=self.ab.cpu_page_size)
                res_val = prg.write_memory(buffer, address)
                if not res_val:
                    break

                self.progress_queue.put(["write", address / self.ih.maxaddr()])
                Clock.schedule_once(self.progress_callback, 1 / 1000)

            """If the write was successful, re-iterate the firmware file, and use the 
               read flash command to update and compare them."""
            if res_val:
                for address in range(0, self.ih.maxaddr(), self.ab.cpu_page_size):
                    buffer = self.ih.tobinarray(start=address, size=self.ab.cpu_page_size)
                    read_buffer = prg.read_memory(address, self.ab.cpu_page_size)
                    if not len(read_buffer) or (buffer != read_buffer):
                        res_val = False
                        break

                    self.progress_queue.put(["read", address / self.ih.maxaddr()])
                    Clock.schedule_once(self.progress_callback, 1 / 1000)

            self.progress_queue.put(["result", "ok" if res_val else "error", address])
            Clock.schedule_once(self.progress_callback, 1 / 1000)

            prg.leave_bootloader()

            prg.close()
        else:
            self.progress_queue.put(["open_error"])
            Clock.schedule_once(self.progress_callback, 1 / 1000)

    def progress_callback(self, dt):
        """In kivy only the main thread can update the widgets. Schedule a clock
           event to read the message from the queue and update the progress."""
        value = self.progress_queue.get()

        if value[0] == "open_error":
            self.root.ids.status.text = "Can't open bootloader {} at baudrate {}".format(self.protocol, self.baudrate)

        if value[0] == "board_request":
            self.root.ids.sw_version.text = self.ab.sw_version
            self.root.ids.hw_version.text = self.ab.hw_version
            self.root.ids.prg_name.text = self.ab.programmer_name

        if value[0] == "cpu_signature":
            self.root.ids.cpu_version.text = self.ab.cpu_name

        if value[0] == "write":
            self.root.ids.status.text = "Writing flash %{:.2f}".format(value[1]*100)
            self.root.ids.progress.value = value[1]

        if value[0] == "read":
            self.root.ids.status.text = "Reading and verifying flash %{:.2f}".format(value[1]*100)
            self.root.ids.progress.value = value[1]

        if value[0] == "result" and value[1] == "ok":
            self.root.ids.status.text = "Download done"
            self.root.ids.progress.value = 1

        if value[0] == "result" and value[1] == "error":
            self.root.ids.status.text = "Error writing"


MainApp().run()
