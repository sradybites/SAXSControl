"""This script creates the SAXS control GUI.

Pollack Lab-Cornell
Alex Mauney
"""

import tkinter as tk
import tkinter.scrolledtext as ScrolledText
from tkinter import filedialog
from widgets import FluidLevel, FlowPath, ElveflowDisplay, TextHandler, MiscLogger, COMPortSelector
import tkinter.ttk as ttk
import time
import SPEC
import FileIO
from configparser import ConfigParser
import logging
import queue
import threading
import SAXSDrivers
import os.path
import csv


FULLSCREEN = True   # For testing, turn this off
LOG_FOLDER = "log"


class main:
    """Class for the main window of the SAXS Control."""

    def __init__(self, window):
        """Set up the window and button variables."""
        print("initializing GUI...")
        os.makedirs(LOG_FOLDER, exist_ok=True)
        os.makedirs(ElveflowDisplay.OUTPUT_FOLDER, exist_ok=True)
        self.main_window = window
        self.main_window.report_callback_exception = self.handle_exception
        self.main_window.title('Main Window')
        self.main_window.attributes("-fullscreen", True)  # Makes the window fullscreen
        # Figure out geometry
        window_width = self.main_window.winfo_screenwidth()
        window_height = self.main_window.winfo_screenheight()
        core_width = round(2*window_width/3)
        log_width = window_width - core_width - 3
        state_height = 300
        core_height = window_height - state_height - 50
        log_height = core_height
        if not FULLSCREEN:
            self.main_window.attributes("-fullscreen", False)  # Makes the window fullscreen
            window_width = self.main_window.winfo_screenwidth() * 2//3
            window_height = self.main_window.winfo_screenheight() * 2//3
            state_height = 1
            core_width = round(2*window_width/3)
            log_width = window_width - core_width - 3
            core_height = window_height - state_height - 50
            log_height = core_height

        # Button Bar
        self.buttons = tk.Frame(self.main_window)
        self.exit_button = tk.Button(self.main_window, text='X', command=self.exit)
        self.stop_button = tk.Button(self.main_window, text='STOP', command=self.stop, fg='red', font='Arial 16 bold')

        # Main Structures
        self.core = ttk.Notebook(self.main_window, width=core_width, height=core_height)
        self.auto_page = tk.Frame(self.core)
        self.config_page = tk.Frame(self.core)
        self.manual_page = tk.Frame(self.core)
        self.setup_page = tk.Frame(self.core)
        self.elveflow_page = tk.Frame(self.core)
        self.logs = ttk.Notebook(self.main_window, width=log_width, height=log_height)
        self.python_logs = tk.Frame(self.logs)
        self.SPEC_logs = tk.Frame(self.logs)
        self.Instrument_logs = tk.Frame(self.logs)
        self.state_frame = tk.Frame(self.main_window, width=window_width, height=state_height, bg='blue')
        # Widgets on Main page
        self.oil_ticksize = tk.IntVar(value=5)
        self.oil_meter = FluidLevel(self.auto_page, color='black', ticksize=self.oil_ticksize)
        self.oil_refill_button = tk.Button(self.auto_page, text='Refill Oil', command=lambda: self.oil_meter.update(100))
        self.oil_start_button = tk.Button(self.auto_page, text='Start Oil', command=self.oil_meter.start)
        self.spec_connect_button = tk.Button(self.auto_page, text='Connect to SPEC', command=self.connect_to_spec)
        self.spec_send_button = tk.Button(self.auto_page, text='Send', command=lambda: self.SPEC_Connection.command(self.spec_command.get()))
        self.spec_command = tk.StringVar(value='')
        self.spec_command_entry = tk.Entry(self.auto_page, textvariable=self.spec_command)
        self.spec_command_entry.bind("<Return>", lambda event: self.SPEC_Connection.command(self.spec_command.get()))
        self.pump_refill_button = tk.Button(self.auto_page, text='Refill Oil', command=lambda: self.pump_refill_command())
        self.pump_inject_button = tk.Button(self.auto_page, text='Run Buffer/Sample/Buffer', command=lambda: self.pump_inject_command())
        # Manual Page
        self.manual_page_buttons = []
        self.manual_page_variables = []
        # Config page

        self.save_config_button = tk.Button(self.config_page, text='Save Config', command=self.save_config)
        self.load_config_button = tk.Button(self.config_page, text='Load Config', command=self.load_config)
        self.config_oil_tick_size_label = tk.Label(self.config_page, text='Oil Use (mL/min)')
        self.config_oil_tick_size = tk.Spinbox(self.config_page, from_=0, to=10, textvariable=self.oil_ticksize, increment=0.01)
        self.spec_address = tk.StringVar(value='192.168.1.5')
        self.volumes_label = tk.Label(self.config_page, text='Buffer/Sample/Buffer volumes in uL:')
        self.first_buffer_volume = tk.IntVar(value=25)     # May need ot be a doublevar
        self.first_buffer_volume_box = tk.Entry(self.config_page, textvariable=self.first_buffer_volume)
        self.sample_volume = tk.IntVar(value=25)           # May need ot be a doublevar
        self.sample_volume_box = tk.Entry(self.config_page, textvariable=self.sample_volume)
        self.last_buffer_volume = tk.IntVar(value=25)      # May need ot be a doublevar
        self.last_buffer_volume_box = tk.Entry(self.config_page, textvariable=self.last_buffer_volume)
        self.oil_valve_names_label = tk.Label(self.config_page, text='Oil Valve Hardware Port Names')
        self.oil_valve_names = []
        self.oil_valve_name_boxes = []
        self.set_oil_valve_names_button = tk.Button(self.config_page, text='Set Names', command=self.set_oil_valve_names)
        self.loading_valve_names_label = tk.Label(self.config_page, text='Loading Valve Hardware Port Names')
        self.loading_valve_names = []
        self.loading_valve_name_boxes = []
        self.set_loading_valve_names_button = tk.Button(self.config_page, text='Set Names', command=self.set_loading_valve_names)
        for i in range(6):
            self.oil_valve_names.append(tk.StringVar(value=''))
            self.oil_valve_name_boxes.append(tk.Entry(self.config_page, textvariable=self.oil_valve_names[i]))
            self.loading_valve_names.append(tk.StringVar(value=''))
            self.loading_valve_name_boxes.append(tk.Entry(self.config_page, textvariable=self.loading_valve_names[i]))
        self.elveflow_sourcename = tk.StringVar()
        self.elveflow_sourcename_label = tk.Label(self.config_page, text='Elveflow sourcename')
        self.elveflow_sourcename_box = tk.Entry(self.config_page, textvariable=self.elveflow_sourcename)
        self.elveflow_sensortypes_label = tk.Label(self.config_page, text='Elveflow sensor types')
        self.elveflow_sensortypes = [tk.StringVar(), tk.StringVar(), tk.StringVar(), tk.StringVar()]
        self.elveflow_sensortypes_optionmenu = [None, None, None, None]
        for i in range(4):
            self.elveflow_sensortypes_optionmenu[i] = tk.OptionMenu(self.config_page, self.elveflow_sensortypes[i], None)
            self.elveflow_sensortypes_optionmenu[i]['menu'].delete(0, 'end')  # there's a default empty option, so get rid of that first
            for item in FileIO.SDK_SENSOR_TYPES:
                self.elveflow_sensortypes_optionmenu[i]['menu'].add_command(label=item,
                                                                            command=lambda i=i, item=item: self.elveflow_sensortypes[i].set(item))  # weird default argument for scoping

        # Make Instrument
        self.AvailablePorts = SAXSDrivers.ListAvailablePorts()
        self.controller = SAXSDrivers.SAXSController(timeout=0.1)
        self.Instruments = []
        self.NumberofPumps = 0
        # Setup Page
        self.AvailablePorts = SAXSDrivers.ListAvailablePorts()
        self.setup_page_buttons = []
        self.setup_page_variables = []
        self.refresh_com_ports = tk.Button(self.setup_page, text="Refresh COM", command=lambda: self.RefreshCOMList())
        self.AddPump = tk.Button(self.setup_page, text="Add Pump", command=lambda: self.AddPumpSetButtons())
        self.AddRheodyne = tk.Button(self.setup_page, text="Add Rheodyne", command=lambda: self.AddRheodyneSetButtons())
        self.AddVICI = tk.Button(self.setup_page, text="Add VICI Valve", command=lambda: self.AddVICISetButtons())
        self.ControllerCOM = COMPortSelector(self.setup_page, exportselection=0, height=3)
        self.ControllerSet = tk.Button(self.setup_page, text="Set Microntroller", command=lambda: self.controller.setport(self.AvailablePorts[int(self.ControllerCOM.curselection()[0])].device))
        self.I2CScanButton = tk.Button(self.setup_page, text="Scan I2C line", command=lambda: self.controller.ScanI2C())
        # self.spec_address = tk.StringVar(value='192.168.0.233')   # For Alex M home use
        self.config_spec_address = tk.Entry(self.config_page, textvariable=self.spec_address)
        self.config_spec_address_label = tk.Label(self.config_page, text='SPEC Address')
        self.spec_port = tk.IntVar(value=7)
        self.config_spec_port = tk.Entry(self.config_page, textvariable=self.spec_port)
        self.config_spec_port_label = tk.Label(self.config_page, text='SPEC Port')
        # logs
        self.python_logger_gui = ScrolledText.ScrolledText(self.python_logs, state='disabled', height=45)
        self.python_logger_gui.configure(font='TkFixedFont')
        self.SPEC_logger = MiscLogger(self.SPEC_logs, state='disabled', height=45)
        self.SPEC_logger.configure(font='TkFixedFont')
        self.Instrument_logger = MiscLogger(self.Instrument_logs, state='disabled', height=45)
        self.Instrument_logger.configure(font='TkFixedFont')
        self.controller.logger = self.Instrument_logger
        #
        # Flow setup frames
        self.flowpath = FlowPath(self.state_frame)
        time.sleep(0.6)   # I have no idea why we need this but everything crashes and burns if we don't include it
        # It acts as though there's a race condition, but aren't we still single-threaded at this point?
        # I suspect something might be going wrong with the libraries, then, especially tkinter and matplotlib
        self.draw_static()
        self.elveflow_display = ElveflowDisplay(self.elveflow_page, core_height, core_width, self.config['Elveflow'], self.python_logger)
        self.elveflow_display.grid(row=0, column=0)
        self.queue = queue.Queue()
        self.queue_busy = False
        self.listen_run_flag = threading.Event()
        self.listen_run_flag.set()
        self.listen_thread = threading.Thread(target=self.listen)
        self.listen_thread.start()
        self.load_config(filename='config.ini')

    def draw_static(self):
        """Define the geometry of the frames and objects."""
        self.stop_button.grid(row=0, column=0, columnspan=2, rowspan=2, sticky='N')
        self.exit_button.grid(row=0, column=1, sticky='NE')
        self.core.grid(row=1, column=0)
        self.logs.grid(row=1, column=1)
        self.state_frame.grid(row=2, column=0, columnspan=2)
        self.stop_button.lift()
        # Main Tab Bar
        self.core.add(self.auto_page, text='Auto')
        self.core.add(self.manual_page, text='Manual')
        self.core.add(self.config_page, text='Config')
        self.core.add(self.setup_page, text='Setup')
        self.core.add(self.elveflow_page, text='Elveflow')
        # Log Tab Bar
        self.logs.add(self.SPEC_logs, text='SPEC')
        self.logs.add(self.python_logs, text='Python')
        self.logs.add(self.Instrument_logs, text='Instruments')
        # Main Page
        self.oil_meter.grid(row=0, columnspan=2)
        self.oil_refill_button.grid(row=1, column=0)
        self.oil_start_button.grid(row=1, column=1)
        self.spec_connect_button.grid(row=2, column=0)
        self.spec_command_entry.grid(row=3, column=0)
        self.spec_send_button.grid(row=3, column=1)
        self.pump_refill_button.grid(row=4, column=0)
        self.pump_inject_button.grid(row=4, column=1)
        # Manual page
        # Config page
        self.save_config_button.grid(row=0, column=0)
        self.load_config_button.grid(row=0, column=1)
        self.config_oil_tick_size_label.grid(row=1, column=0)
        self.config_oil_tick_size.grid(row=1, column=1)
        self.config_spec_address_label.grid(row=2, column=0)
        self.config_spec_address.grid(row=2, column=1)
        self.config_spec_port_label.grid(row=3, column=0)
        self.config_spec_port.grid(row=3, column=1)
        self.volumes_label.grid(row=4, column=0)
        self.first_buffer_volume_box.grid(row=4, column=1)
        self.sample_volume_box.grid(row=4, column=2)
        self.last_buffer_volume_box.grid(row=4, column=3)
        self.oil_valve_names_label.grid(row=5, column=0)
        self.set_oil_valve_names_button.grid(row=5, column=7)
        self.loading_valve_names_label.grid(row=6, column=0)
        self.set_loading_valve_names_button.grid(row=6, column=7)
        for i in range(6):
            self.oil_valve_name_boxes[i].grid(row=5, column=i+1)
            self.loading_valve_name_boxes[i].grid(row=6, column=i+1)
        self.elveflow_sourcename_label.grid(row=7, column=0)
        self.elveflow_sourcename_box.grid(row=7, column=1)
        self.elveflow_sensortypes_label.grid(row=8, column=0)
        for i in range(4):
            self.elveflow_sensortypes_optionmenu[i].grid(row=8, column=i+1)

        # Setup page
        self.refresh_com_ports.grid(row=0, column=0)
        self.AddPump.grid(row=0, column=2)
        self.AddRheodyne.grid(row=0, column=3)
        self.AddVICI.grid(row=0, column=4)
        self.ControllerCOM.grid(row=1, column=0)
        self.ControllerSet.grid(row=1, column=2)
        self.I2CScanButton.grid(row=1, column=3)
        self.RefreshCOMList()
        # FlowPath
        self.flowpath.grid(row=0, column=0)
        # Python Log
        self.python_logger_gui.grid(row=0, column=0, sticky='NSEW')
        nowtime = time.time()
        python_handler = TextHandler(self.python_logger_gui)
        file_handler = logging.FileHandler(os.path.join(LOG_FOLDER, "log%010d.txt" % nowtime))
        python_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        python_handler.setLevel(logging.DEBUG)
        file_handler.setLevel(logging.DEBUG)
        # SPEC Log
        self.SPEC_logger.grid(row=0, column=0, sticky='NSEW')
        self.SPEC_Connection = SPEC.connection(logger=self.SPEC_logger, button=self.spec_connect_button)
        self.Instrument_logger.grid(row=0, column=0, sticky='NSEW')
        # logging.basicConfig(level=logging.INFO,
        #                     format='%(asctime)s - %(levelname)s - %(message)s')
        self.python_logger = logging.getLogger("python")
        self.python_logger.setLevel(logging.DEBUG)
        self.python_logger.addHandler(python_handler)  # logging to the screen
        self.python_logger.addHandler(file_handler)  # logging to a file

    def stop(self):
        """Stop all running widgets."""
        self.oil_meter.stop()
        with self.queue.mutex:
            self.queue.queue.clear()
        SAXSDrivers.InstrumentTerminateFunction(self.Instruments)
        # Add Elveflow stop if we use it for non-pressure

    def load_config(self, filename=None):
        """Load a config.ini file."""
        self.config = ConfigParser()
        if filename is None:
            filename = filedialog.askopenfilename(initialdir=".", title="Select file", filetypes=(("config files", "*.ini"), ("all files", "*.*")))
        if filename != '':
            self.config.read(filename, encoding='utf-8')
            # TODO: there's a race condition here
            time.sleep(0.5)
            oil_config = self.config['Oil Valve']
            loading_config = self.config['Loading Valve']
            main_config = self.config['Main']
            elveflow_config = self.config['Elveflow']
            self.sucrose = main_config.getboolean('Sucrose', False)
            for i in range(0, 6):
                field = 'name'+str(i+1)
                self.oil_valve_name_boxes[i].delete(0, 'end')
                self.oil_valve_name_boxes[i].insert(0, oil_config.get(field, ''))
                self.loading_valve_name_boxes[i].delete(0, 'end')
                self.loading_valve_name_boxes[i].insert(0, loading_config.get(field, ''))
            self.elveflow_sourcename.set(elveflow_config['elveflow_sourcename'])
            self.elveflow_sensortypes[0].set(elveflow_config['sensor1_type'])
            self.elveflow_sensortypes[1].set(elveflow_config['sensor2_type'])
            self.elveflow_sensortypes[2].set(elveflow_config['sensor3_type'])
            self.elveflow_sensortypes[3].set(elveflow_config['sensor4_type'])
        if not preload:
            self.set_oil_valve_names()
            self.set_loading_valve_names()

    def save_config(self):
        """Save a config.ini file."""
        filename = filedialog.asksaveasfilename(initialdir=".", title="Select file", filetypes=(("config files", "*.ini"), ("all files", "*.*")))
        if filename is not '':
            self.config.write(open(filename, 'w'))

    def connect_to_spec(self):
        """Connect to SPEC instance."""
        self.SPEC_Connection.connect((self.spec_address.get(), self.spec_port.get()))

    def handle_exception(self, exception, value, traceback):
        """Add python exceptions to the GUI log."""
        self.python_logger.exception("Caught exception:")

    def save_history(self, filename=None):
        """Save a csv file with the current state."""
        if filename is None:
            filename = filedialog.asksaveasfilename(initialdir=".", title="Save file", filetypes=(("comma-separated value", "*.csv"), ("all files", "*.*")))
        if filename == '':
            # empty filename: don't save
            return
        with open(filename, 'w') as f:
            csvwriter = csv.writer(f)
            csvwriter.writerow(main.CSV_HEADERS)
            csvwriter.writerows(self.history)

    def exit(self):
        """Exit the GUI and stop all running things"""
        print("STARTING EXIT PROCEDURE")
        self.stop()
        if self.elveflow_display.run_flag.is_set():
            self.elveflow_display.stop(shutdown=True)
        if self.SPEC_Connection.run_flag.is_set():
            self.SPEC_Connection.stop()
        if self.listen_run_flag.is_set():
            self.listen_run_flag.clear()
        self.main_window.destroy()

    def pump_refill_command(self):
        """Do nothing. It's a dummy command."""
        self.flowpath.set_unlock_state(False)
        self.queue.put((self.elveflow_display.elveflow_handler.setPressure, 4, 100))  # Pressurize Oil with Elveflow
        #   Switch valve (may be hooked to pump)
        self.queue.put(self.pump.set_mode_vol)
        self.queue.put((time.sleep, 0.1))
        self.queue.put(self.pump.refill)    # Set pump refill params
        self.queue.put((time.sleep, 0.1))
        self.queue.put((self.pump.set_target_vol, (self.first_buffer_volume.get()+self.sample_volume.get()+self.last_buffer_volume.get())/1000))
        self.queue.put((time.sleep, 0.1))
        self.queue.put(self.pump.start_pump)     # Refill pump
        self.queue.put((time.sleep, 10))
        self.queue.put(self.pump.infuse)    # Set pump to injection mode
        #   Switch valve
        self.queue.put((self.elveflow_display.elveflow_handler.setPressure, 4, 0))  # Vent Oil
        pass

    def pump_inject_command(self):
        """Do nothing. It's a dummy command."""
        self.flowpath.set_unlock_state(False)
        self.queue.put(self.pump.set_mode_vol)
        self.queue.put((time.sleep, 0.1))
        self.queue.put(self.pump.infuse)  # Set pump refill params
        self.queue.put((time.sleep, 0.1))
        self.queue.put((self.pump.set_target_vol, self.first_buffer_volume.get()/1000))
        self.queue.put((time.sleep, 0.1))
        self.queue.put(self.pump.start_pump)
        self.queue.put((time.sleep, 10))
        self.queue.put((self.pump.set_target_vol, self.sample_volume.get()/1000))
        self.queue.put((time.sleep, 0.1))
        self.queue.put(self.pump.start_pump)
        self.queue.put((time.sleep, 10))
        self.queue.put((self.pump.set_target_vol, self.last_buffer_volume.get()/1000))
        self.queue.put((time.sleep, 0.1))
        self.queue.put(self.pump.start_pump)
        #   Check valve positions
        #   Inject X uL
        #   Switch sample valve to sample loop
        #   Inject Y uL
        #   Switch sample valve to buffer positions
        #   Inject Z uL
        pass

    def listen(self):
        """Look for queues of hardware commands and execute them."""
        print("STARTING QUEUE LISTENING THREAD %s" % threading.current_thread())
        while self.listen_run_flag.is_set():
            if self.queue.empty():
                if self.queue_busy:
                    self.queue_busy = False
                    self.toggle_buttons()
            else:
                if not self.queue_busy:
                    self.queue_busy = True
                    self.toggle_buttons()
                queue_item = self.queue.get()
                if isinstance(queue_item, tuple):
                    queue_item[0](*queue_item[1:])
                elif callable(queue_item):
                    queue_item()
        print("DONE WITH THIS QUEUE LISTENING THREAD %s" % threading.current_thread())

    def toggle_buttons(self):
        """Toggle certain buttons on and off when they should not be allowed to add to queue."""
        buttons = (self.pump_inject_button,
                   self.pump_refill_button)
        if self.queue_busy:
            for button in buttons:
                button['state'] = 'disabled'
        else:
            for button in buttons:
                button['state'] = 'normal'

    def AddPumpSetButtons(self):
        self.Instruments.append(SAXSDrivers.HPump(logger=self.Instrument_logger))
        self.NumberofPumps += 1
        InstrumentIndex = len(self.Instruments)-1

        newvars = [tk.IntVar(value=0), tk.StringVar()]
        self.setup_page_variables.append(newvars)

        newbuttons = [
         COMPortSelector(self.setup_page, exportselection=0, height=4),
         tk.Button(self.setup_page, text="Set Port", command=lambda: self.Instruments[InstrumentIndex].setport(self.AvailablePorts[int(self.setup_page_buttons[InstrumentIndex][0].curselection()[0])].device)),
         tk.Label(self.setup_page, text="or"),
         tk.Button(self.setup_page, text="Send to Controller", command=lambda: self.Instruments[InstrumentIndex].settocontroller(self.controller)),
         tk.Label(self.setup_page, text="   Pump Address:"),
         tk.Spinbox(self.setup_page, from_=1, to=100, textvariable=self.setup_page_variables[InstrumentIndex][0]),
         tk.Label(self.setup_page, text="   Pump Name:"),
         tk.Entry(self.setup_page, textvariable=self.setup_page_variables[InstrumentIndex][1]),
         tk.Button(self.setup_page, text="Set values", command=lambda: self.InstrumentChangeValues(InstrumentIndex))
         ]

        # Pumps share a port-> Dont need extra ones
        if self.NumberofPumps > 1:
            newbuttons[0] = tk.Label(self.setup_page, text="     ")
            newbuttons[1] = tk.Label(self.setup_page, text="     ")
            newbuttons[2] = tk.Label(self.setup_page, text="     ")

        self.setup_page_buttons.append(newbuttons)
        for i in range(len(self.setup_page_buttons)):
            for y in range(len(self.setup_page_buttons[i])):
                self.setup_page_buttons[i][y].grid(row=i+2, column=y)
        self.RefreshCOMList()
        self.AddPumpControlButtons()

    def InstrumentChangeValues(self, InstrumentIndex, isvalve=False):
        self.Instruments[InstrumentIndex].changevalues(int((self.setup_page_variables[InstrumentIndex][0]).get()), (self.setup_page_variables[InstrumentIndex][1]).get())
        self.manual_page_variables[InstrumentIndex][0].set(self.Instruments[InstrumentIndex].name+":  ")
        if isvalve:
            self.manual_page_buttons[InstrumentIndex][2].config(to=self.setup_page_variables[InstrumentIndex][2].get())

    def AddPumpControlButtons(self):
        InstrumentIndex = len(self.Instruments)-1
        newvars = [tk.StringVar(), tk.DoubleVar(value=0), tk.DoubleVar(value=0), tk.DoubleVar(value=0)]
        newvars[0].set(self.Instruments[InstrumentIndex].name+":  ")
        self.manual_page_variables.append(newvars)
        newbuttons = [
         tk.Label(self.manual_page, textvariable=self.manual_page_variables[InstrumentIndex][0]),
         tk.Button(self.manual_page, text="Run", command=lambda: self.Instruments[InstrumentIndex].startpump()),
         tk.Button(self.manual_page, text="Stop", command=lambda:self.Instruments[InstrumentIndex].stoppump()),
         tk.Label(self.manual_page, text="  Infuse Rate:"),
         tk.Spinbox(self.manual_page, from_=0, to=1000, textvariable=self.manual_page_variables[InstrumentIndex][1]),
         tk.Button(self.manual_page, text="Set"),
         tk.Label(self.manual_page, text="  Refill Rate:"),
         tk.Spinbox(self.manual_page, from_=0, to=1000, textvariable=self.manual_page_variables[InstrumentIndex][2]),
         tk.Button(self.manual_page, text="Set"),
         tk.Label(self.manual_page, text="  Direction:"),
         tk.Button(self.manual_page, text="Infuse"),
         tk.Button(self.manual_page, text="Refill"),
         tk.Label(self.manual_page, text="Mode"),
         tk.Button(self.manual_page, text="Pump"),
         tk.Button(self.manual_page, text="Vol"),
         tk.Label(self.manual_page, text="  Target Vol:"),
         tk.Spinbox(self.manual_page, from_=0, to=1000, textvariable=self.manual_page_variables[InstrumentIndex][3]),
         tk.Button(self.manual_page, text="Set")
         ]
        self.manual_page_buttons.append(newbuttons)
        # Build Pump
        for i in range(len(self.manual_page_buttons)):
            for y in range(len(self.manual_page_buttons[i])):
                self.manual_page_buttons[i][y].grid(row=i, column=y)

    def RefreshCOMList(self):
        self.ControllerCOM.updatelist(SAXSDrivers.ListAvailablePorts(self.AvailablePorts))
        for button in self.setup_page_buttons:
            if isinstance(button[0], COMPortSelector):
                button[0].updatelist(SAXSDrivers.ListAvailablePorts(self.AvailablePorts))

    def AddRheodyneSetButtons(self):
        self.Instruments.append(SAXSDrivers.Rheodyne(logger=self.Instrument_logger))
        InstrumentIndex = len(self.Instruments)-1
        newvars = [tk.IntVar(value=-1), tk.StringVar(), tk.IntVar(value=2)]
        self.setup_page_variables.append(newvars)
        newbuttons = [
         COMPortSelector(self.setup_page, exportselection=0, height=4),
         tk.Button(self.setup_page, text="Set Port", command=lambda: self.Instruments[InstrumentIndex].setport(self.AvailablePorts[int(self.setup_page_buttons[InstrumentIndex][0].curselection()[0])].device)),
         tk.Label(self.setup_page, text="or"),
         tk.Button(self.setup_page, text="Send to Controller", command=lambda: self.Instruments[InstrumentIndex].settocontroller(self.controller)),
         tk.Label(self.setup_page, text="   Type:"),
         tk.Spinbox(self.setup_page, values=(2, 6), textvariable=self.setup_page_variables[InstrumentIndex][2]),
         tk.Label(self.setup_page, text="   I2C Address:"),
         tk.Spinbox(self.setup_page, from_=-1, to=100, textvariable=self.setup_page_variables[InstrumentIndex][0]),
         tk.Label(self.setup_page, text="   Valve Name:"),
         tk.Entry(self.setup_page, textvariable=self.setup_page_variables[InstrumentIndex][1]),
         tk.Button(self.setup_page, text="Set values", command=lambda: self.InstrumentChangeValues(InstrumentIndex, True))
         ]
        self.setup_page_buttons.append(newbuttons)
        for i in range(len(self.setup_page_buttons)):
            for y in range(len(self.setup_page_buttons[i])):
                self.setup_page_buttons[i][y].grid(row=i+2, column=y)
        self.AddRheodyneControlButtons()
        self.RefreshCOMList()

    def AddRheodyneControlButtons(self):
        InstrumentIndex = len(self.Instruments)-1
        newvars = [tk.StringVar(), tk.IntVar(value=0)]
        newvars[0].set(self.Instruments[InstrumentIndex].name+":  ")
        self.manual_page_variables.append(newvars)

        newbuttons = [
         tk.Label(self.manual_page, textvariable=self.manual_page_variables[InstrumentIndex][0]),
         tk.Label(self.manual_page, text="   Position:"),
         tk.Spinbox(self.manual_page, from_=1, to=self.setup_page_variables[InstrumentIndex][2].get(), textvariable=self.manual_page_variables[InstrumentIndex][1]),
         tk.Button(self.manual_page, text="Change", command=lambda: self.Instruments[InstrumentIndex].switchvalve(self.manual_page_variables[InstrumentIndex][1].get())),
         ]
        self.manual_page_buttons.append(newbuttons)
        # Place buttons
        for i in range(len(self.manual_page_buttons)):
            for y in range(len(self.manual_page_buttons[i])):
                self.manual_page_buttons[i][y].grid(row=i, column=y)

    def AddVICISetButtons(self):
        self.Instruments.append(SAXSDrivers.VICI(logger=self.Instrument_logger))
        InstrumentIndex = len(self.Instruments)-1
        newvars = [tk.IntVar(value=-1), tk.StringVar()]
        self.setup_page_variables.append(newvars)
        newbuttons = [
         COMPortSelector(self.setup_page, exportselection=0, height=4),
         tk.Button(self.setup_page, text="Set Port", command=lambda: self.Instruments[InstrumentIndex].setport(self.AvailablePorts[int(self.setup_page_buttons[InstrumentIndex][0].curselection()[0])].device)),
         tk.Label(self.setup_page, text="or"),
         tk.Button(self.setup_page, text="Send to Controller", command=lambda:self.Instruments[InstrumentIndex].settocontroller(self.controller)),
         tk.Label(self.setup_page, text="   Valve Name:"),
         tk.Entry(self.setup_page, textvariable=self.setup_page_variables[InstrumentIndex][1]),
         tk.Button(self.setup_page, text="Set values", command=lambda: self.InstrumentChangeValues(InstrumentIndex, False))
         ]
        self.setup_page_buttons.append(newbuttons)
        for i in range(len(self.setup_page_buttons)):
            for y in range(len(self.setup_page_buttons[i])):
                self.setup_page_buttons[i][y].grid(row=i+2, column=y)
        self.AddVICIControlButtons()
        self.RefreshCOMList()

    def AddVICIControlButtons(self):
        InstrumentIndex = len(self.Instruments)-1
        newvars = [tk.StringVar(), tk.StringVar(value="A")]
        newvars[0].set(self.Instruments[InstrumentIndex].name+":  ")
        self.manual_page_variables.append(newvars)

        newbuttons = [
         tk.Label(self.manual_page, textvariable=self.manual_page_variables[InstrumentIndex][0]),
         tk.Label(self.manual_page, text="   Position:"),
         tk.Spinbox(self.manual_page, values=("A", "B"), textvariable=self.manual_page_variables[InstrumentIndex][1]),
         tk.Button(self.manual_page, text="Change", command=lambda: self.Instruments[InstrumentIndex].switchvalve(self.manual_page_variables[InstrumentIndex][1].get())),
         ]
        self.manual_page_buttons.append(newbuttons)
        # Place buttons
        for i in range(len(self.manual_page_buttons)):
            for y in range(len(self.manual_page_buttons[i])):
                self.manual_page_buttons[i][y].grid(row=i, column=y)


if __name__ == "__main__":
    window = tk.Tk()
    main(window)
    window.mainloop()
    print("Main window now destroyed. Exiting.")
