"""This script creates a simple SAXS gui
Controls, hardvard syringe pumps and valves

Pollack Lab-Cornell
Josue San Emeterio
"""



import tkinter as tk
from tkinter import messagebox
import tkinter.ttk as ttk
import time
from widgets import COMPortSelector, ConsoleUi
import logging
import winsound
import random
import threading
from hardware import SAXSDrivers, solocomm
import os.path
import csv
import numpy as np
import warnings

FULLSCREEN = False   # For testing, turn this off

# TODO: hardcode variables and get rid of all magic numbers
# TODO: design an actual object hierarchy to organize code
class Main:
    """Represents the software for controlling the beamline
    setup colloquially known as 'the Cube.'

    ...

    Attributes (non-trivial)
    ----------
    _lock : threading.RLock
        a repeatable lock used for thread-safe access of the interface
    python_logger : logging.Logger
        python logger for debugging, errors, etc
    main_window : tkinter.Tk
        top-level application window
    listen_run_flag : threading.Event
        flag that instructs the control threads to keep running

    """

    def __init__(self, window):
        """Create a new Main object using the given tkinter window.

        Sets up the window and button variables. Sets up the control interface
        by page, of which there are four:

            Auto: simple, <10 buttons for abstract control of pumps/valves
            Manual: indiscreet set of buttons allowing meticulous control
            Config: set various parameters for the setup, including valve
                positions, loop volumes, and execution lengths
            Setup: configure connections between all the various devices in
                the setup
        """

        self._lock = threading.RLock() # repeatable lock for thread-safe access
        self.python_logger = logging.getLogger("python") # create logger named "python"

        self.adxIsDone = False # not sure what this is for? not used at all in this file
        self.illegal_chars = '!@#$%^&*()."\\|:;<>?=~ ' + "'"

        self.main_window = window
        self.main_window.report_callback_exception = self.handle_exception
        self.main_window.title('Main Window')
        self.main_window.attributes("-fullscreen", True)  # Makes the window fullscreen

        # Set window dimensions
        window_width = self.main_window.winfo_screenwidth()
        window_height = self.main_window.winfo_screenheight()
        core_width = round(2*window_width/3)
        log_width = window_width - core_width - 10
        state_height = 400
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

        # Make it pretty
        self.gui_bg_color = "thistle3"
        self.label_bg_color = self.gui_bg_color

        self.main_window.configure(bg=self.gui_bg_color)
        ttk.Style().configure("TNotebook", background=self.gui_bg_color)

        # Button Bar
        self.buttons = tk.Frame(self.main_window)
        self.exit_button = tk.Button(self.main_window, text='X', command=self.exit_)
        self.stop_button = tk.Button(self.main_window, text='STOP', command=self.stop, fg='red', font='Arial 16 bold')

        # Main Structures
        self.core = ttk.Notebook(self.main_window, width=core_width, height=core_height)
        self.auto_page = tk.Frame(self.core, bg=self.gui_bg_color)
        self.config_page = tk.Frame(self.core, bg=self.gui_bg_color)
        self.manual_page = tk.Frame(self.core, bg=self.gui_bg_color)
        self.setup_page = tk.Frame(self.core, bg=self.gui_bg_color)
        self.logs = ttk.Notebook(self.main_window, width=log_width, height=log_height)
        self.user_logs = tk.Frame(self.logs)
        self.advanced_logs = tk.Frame(self.logs)


        ### Auto Page ###
        auto_button_font = 'Arial 20 bold'
        auto_button_half_font = 'Arial 14 bold'
        auto_button_width = 14
        auto_color = "white"
        self.running_pos = "" # represents the valve position(s)/configuration. takes two values: "buffer" and "sample". TODO: make possible values explicit with custom Enum class
        self.auto_flowrate_variable = tk.DoubleVar()
        self.run_buffer = tk.Button(self.auto_page, text="Set Buffer", font=auto_button_font, width=auto_button_width, height=3, bg=auto_color, command=self.run_buffer_command)  # Maybe sets flowpath but doesnt start pumps?
        self.run_sample = tk.Button(self.auto_page, text="Set Sample", font=auto_button_font, width=auto_button_width, height=3, bg=auto_color, command=self.run_sample_command)  # ""
        # self.pause_pump = tk.Button(self.auto_page, text="Pause Pumps", font=auto_button_font, width=auto_button_width, height=3, bg=auto_color)  # This button pauses pumps between switching possitions. Should update infused vol
        self.run_pumps = tk.Button(self.auto_page, text="Run Pumps", font=auto_button_font, width=auto_button_width*2+2, height=3, command=self.run_pumps_button_command, bg="red", fg="white")  # This button is to restart pumps after pause. It needs to check for valve possitions, before starting.
        self.remaining_buffer_vol_var = tk.DoubleVar()
        self.remaining_buffer_real = 0
        self.remaining_sample_real = 0
        self.oil_used = 0.0
        self.oil_used_var = tk.DoubleVar()
        self.oil_used_label = tk.Label(self.auto_page, font=auto_button_half_font, text="Oil Used:", bg=auto_color)
        self.oil_used_vol = tk.Label(self.auto_page, font=auto_button_font, textvariable=self.oil_used_var)
        self.remaining_sample = tk.Label(self.auto_page, font=auto_button_half_font, text="Remaining Sample:", bg=auto_color)
        self.remaining_sample_vol_var = tk.DoubleVar()
        self.remaining_buffer = tk.Label(self.auto_page, font=auto_button_half_font, text="Remaining Buffer:", bg=auto_color)
        self.remaining_sample = tk.Label(self.auto_page, font=auto_button_half_font, text="Remaining Sample:", bg=auto_color)
        self.remaining_buffer_vol = tk.Label(self.auto_page, font=auto_button_font, textvariable=self.remaining_buffer_vol_var)
        self.remaining_sample_vol = tk.Label(self.auto_page, font=auto_button_font, textvariable=self.remaining_sample_vol_var)
        self.clean_button = tk.Button(self.auto_page, text='Clean', font=auto_button_font, width=auto_button_width, height=3, bg=auto_color, command=self.clean_only_command)
        # FIXME: the "Clean+Refill" button only refills
        self.refill_button = tk.Button(self.auto_page, text="Clean+Refill", font=auto_button_font, width=auto_button_width, height=3, bg=auto_color, command=self.refill_only_command)
        self.set_main_flowrate = tk.Button(self.auto_page, text='Set Flowrate', font=auto_button_font, width=auto_button_width, height=3, bg=auto_color, command=self.set_auto_flowrate_command)
        self.main_flowrate = tk.Spinbox(self.auto_page, from_=0, to_=100, textvariable=self.auto_flowrate_variable, font='Arial 30 bold', width = 10, bg=auto_color, justify="right")
        self.pumps_running_bool = False
        self.load_buffer_button = tk.Button(self.auto_page, text="Load Buffer", font=auto_button_font, width=auto_button_width, height=3, bg=auto_color, command=self.load_buffer_command)
        self.load_sample_button = tk.Button(self.auto_page, text="Load Sample", font=auto_button_font, width=auto_button_width, height=3, bg=auto_color, command=self.load_sample_command)

        ### Manual Page ###
        self.manual_button_font = 'Arial 10 bold'
        self.clean_sample_button = tk.Button(self.manual_page, text='Clean Sample', command=lambda: self.clean_loop(1), font=auto_button_font, width=auto_button_width+2)
        self.manual_page_buttons = []
        self.manual_page_variables = []

        self.purge_button = tk.Button(self.manual_page, text='Purge', command=self.purge_command, font=auto_button_font, width=auto_button_width, height=3)
        self.purge_soap_button = tk.Button(self.manual_page, text='Purge Soap', command=self.purge_soap_command, font=auto_button_font, width=auto_button_width)
        self.purge_dry_button = tk.Button(self.manual_page, text='Dry Sheath', command=self.purge_dry_command, font=auto_button_font, width=auto_button_width)

        self.purge_insert_soap_button = tk.Button(self.manual_page, text='Soap insert', command=lambda: self.insert_purge("Soap"), font=auto_button_font, width=auto_button_width+2)
        self.purge_insert_water_button = tk.Button(self.manual_page, text='Water insert', command=lambda: self.insert_purge("Water"), font=auto_button_font, width=auto_button_width+2)
        self.purge_sheath_insert_soap_button = tk.Button(self.manual_page, text='Soap insert sheath', command=lambda: self.insert_sheath_purge("Soap"), font=auto_button_font, width=auto_button_width+5)
        self.purge_sheath_insert_water_button = tk.Button(self.manual_page, text='Water insert sheath', command=lambda: self.insert_sheath_purge("Water"), font=auto_button_font, width=auto_button_width+5)

        # Purge Configs

        self.purge_possition_label = tk.Label(self.config_page, text="Purge valve positions:", bg=self.label_bg_color, width = 3)
        self.purge_running_label = tk.Label(self.config_page, text="running:", bg=self.label_bg_color)
        self.purge_running_pos = tk.IntVar(value=2)
        self.purge_running_box = tk.Spinbox(self.config_page, from_=0, to=100, textvariable=self.purge_running_pos, width = 3)

        self.purge_water_label = tk.Label(self.config_page, text="Water Purge:", bg=self.label_bg_color)
        self.purge_water_pos = tk.IntVar(value=3)
        self.purge_water_box = tk.Spinbox(self.config_page, from_=0, to=100, textvariable=self.purge_water_pos, width = 3)

        self.purge_soap_label = tk.Label(self.config_page, text="Soap:", bg=self.label_bg_color)
        self.purge_soap_pos = tk.IntVar(value=4)
        self.purge_soap_box = tk.Spinbox(self.config_page, from_=0, to=100, textvariable=self.purge_soap_pos, width = 3)

        self.purge_air_label = tk.Label(self.config_page, text="Air:", bg=self.label_bg_color)
        self.purge_air_pos = tk.IntVar(value=1)
        self.purge_air_box = tk.Spinbox(self.config_page, from_=0, to=100, textvariable=self.purge_air_pos, width = 3)




        ### Config Page ###
        # FIXME: not all variables have unit labels, which creates ambiguity
        self.config = None
        self.oil_valve_names_label =tk.Label(self.config_page,text="Oil Valve Configuration:", bg=self.gui_bg_color)
        self.coil_valve_names_label =tk.Label(self.config_page,text="Cerberus Oil Valve Configuration:", bg=self.gui_bg_color)
        self.loading_valve_names_label =tk.Label(self.config_page,text="Loading Valve Configuration:", bg=self.gui_bg_color)
        self.cerberus_loading_valve_names_label = tk.Label(self.config_page,text="Cerberus Loading Valve Configuration:", bg=self.gui_bg_color)
        self.refill_rate = 150
        # Loading valve possitions
        # Variables
        self.loading_cell_var = tk.IntVar()
        self.loading_load_var = tk.IntVar()
        self.loading_HSoap_var = tk.IntVar()
        self.loading_LSoap_var = tk.IntVar()
        self.loading_Water_var = tk.IntVar()
        self.loading_Air_var = tk.IntVar()
        # set Variables
        self.loading_cell_var.set(2)
        self.loading_load_var.set(3)
        self.loading_HSoap_var.set(6)
        self.loading_LSoap_var.set(1)
        self.loading_Water_var.set(5)
        self.loading_Air_var.set(4)

        # Entry
        self.loading_cell_entry = tk.Spinbox(self.config_page, textvariable=self.loading_cell_var, width=3)
        self.loading_load_entry = tk.Spinbox(self.config_page, textvariable=self.loading_load_var, width=3)
        self.loading_HSoap_entry = tk.Spinbox(self.config_page, textvariable=self.loading_HSoap_var, width=3)
        self.loading_LSoap_entry = tk.Spinbox(self.config_page, textvariable=self.loading_LSoap_var, width=3)
        self.loading_Water_entry = tk.Spinbox(self.config_page, textvariable=self.loading_Water_var, width=3)
        self.loading_Air_entry = tk.Spinbox(self.config_page, textvariable=self.loading_Air_var, width=3)
        # Labels
        self.loading_cell_label = tk.Label(self.config_page, text="Cell:", bg=self.gui_bg_color)
        self.loading_load_label = tk.Label(self.config_page, text="Loading:", bg=self.gui_bg_color)
        self.loading_HSoap_label = tk.Label(self.config_page, text="High Soap:", bg=self.gui_bg_color)
        self.loading_LSoap_label = tk.Label(self.config_page, text="Low Soap:", bg=self.gui_bg_color)
        self.loading_Water_label = tk.Label(self.config_page, text="Water:", bg=self.gui_bg_color)
        self.loading_Air_label = tk.Label(self.config_page, text="Air:", bg=self.gui_bg_color)

        # Cerberus Loading Valve Possition
        # Variables
        self.cerberus_loading_cell_var = tk.IntVar()
        self.cerberus_loading_load_var = tk.IntVar()
        self.cerberus_loading_HSoap_var = tk.IntVar()
        self.cerberus_loading_LSoap_var = tk.IntVar()
        self.cerberus_loading_Water_var = tk.IntVar()
        self.cerberus_loading_Air_var = tk.IntVar()
        # Set the variables
        self.cerberus_loading_cell_var.set(1)
        self.cerberus_loading_load_var.set(6)
        self.cerberus_loading_HSoap_var.set(3)
        self.cerberus_loading_LSoap_var.set(2)
        self.cerberus_loading_Water_var.set(4)
        self.cerberus_loading_Air_var.set(5)
        # Entry
        self.cerberus_loading_cell_entry = tk.Spinbox(self.config_page, textvariable=self.cerberus_loading_cell_var, width=3)
        self.cerberus_loading_load_entry = tk.Spinbox(self.config_page, textvariable=self.cerberus_loading_load_var, width=3)
        self.cerberus_loading_HSoap_entry = tk.Spinbox(self.config_page, textvariable=self.cerberus_loading_HSoap_var, width=3)
        self.cerberus_loading_LSoap_entry = tk.Spinbox(self.config_page, textvariable=self.cerberus_loading_LSoap_var, width=3)
        self.cerberus_loading_Water_entry = tk.Spinbox(self.config_page, textvariable=self.cerberus_loading_Water_var, width=3)
        self.cerberus_loading_Air_entry = tk.Spinbox(self.config_page, textvariable=self.cerberus_loading_Air_var, width=3)
        # labels
        self.cerberus_loading_cell_label = tk.Label(self.config_page, text="Cell:", bg=self.gui_bg_color)
        self.cerberus_loading_load_label = tk.Label(self.config_page, text="Loading:", bg=self.gui_bg_color)
        self.cerberus_loading_HSoap_label = tk.Label(self.config_page, text="High Soap:", bg=self.gui_bg_color)
        self.cerberus_loading_LSoap_label = tk.Label(self.config_page, text="Low Soap:", bg=self.gui_bg_color)
        self.cerberus_loading_Water_label = tk.Label(self.config_page, text="Water:", bg=self.gui_bg_color)
        self.cerberus_loading_Air_label = tk.Label(self.config_page, text="Air:", bg=self.gui_bg_color)

        # Loading Valve Possitions
        self.oil_pump_var = tk.IntVar()
        self.oil_waste_var = tk.IntVar()
        self.oil_insertpurge_var = tk.IntVar()
        self.oil_pump_var.set(4)
        self.oil_waste_var.set(5)
        self.oil_insertpurge_var.set(1)

        self.oil_pump_entry = tk.Spinbox(self.config_page, textvariable=self.oil_pump_var, width=3)
        self.oil_waste_entry = tk.Spinbox(self.config_page, textvariable=self.oil_waste_var, width=3)
        self.oil_insertpurge_entry = tk.Spinbox(self.config_page, textvariable=self.oil_insertpurge_var, width=3)

        self.oil_pump_label = tk.Label(self.config_page, text="Pump", bg=self.gui_bg_color)
        self.oil_waste_label = tk.Label(self.config_page, text="Waste", bg=self.gui_bg_color)
        self.oil_insertpurge_label = tk.Label(self.config_page, text="Insert Purge", bg=self.gui_bg_color)
        # Cerberus Loading Valve Possitions
        self.cerberus_oil_pump_var = tk.IntVar()
        self.cerberus_oil_waste_var = tk.IntVar()
        self.cerberus_oil_insertpurge_var = tk.IntVar()
        self.cerberus_oil_pump_var.set(3)
        self.cerberus_oil_waste_var.set(2)
        self.cerberus_oil_insertpurge_var.set(4)

        self.cerberus_oil_pump_entry = tk.Spinbox(self.config_page, textvariable=self.cerberus_oil_pump_var, width=3)
        self.cerberus_oil_waste_entry = tk.Spinbox(self.config_page, textvariable=self.cerberus_oil_waste_var, width=3)
        self.cerberus_oil_insertpurge_entry = tk.Spinbox(self.config_page, textvariable=self.cerberus_oil_insertpurge_var, width=3)

        self.cerberus_oil_pump_label = tk.Label(self.config_page, text="Pump", bg=self.gui_bg_color)
        self.cerberus_oil_waste_label = tk.Label(self.config_page, text="Waste", bg=self.gui_bg_color)
        self.cerberus_oil_insertpurge_label = tk.Label(self.config_page, text="Insert Purge", bg=self.gui_bg_color)

        # Cleaning Times:
        self.cleaning_config_label = tk.Label(self.config_page, text="Cleaning Parameters:",  bg=self.gui_bg_color)
        self.low_soap_time_label = tk.Label(self.config_page, text="Low soap time:", bg=self.label_bg_color)
        self.low_soap_time = tk.IntVar(value=15)
        self.low_soap_time_box = tk.Spinbox(self.config_page, from_=0, to=1000, width=3, textvariable=self.low_soap_time)
        self.high_soap_time_label = tk.Label(self.config_page, text="High soap time:", bg=self.label_bg_color)
        self.high_soap_time = tk.IntVar(value=15)
        self.high_soap_time_box = tk.Spinbox(self.config_page, from_=0, to=1000, width=3, textvariable=self.high_soap_time)
        self.water_time_label = tk.Label(self.config_page, text="Water time:", bg=self.label_bg_color)
        self.water_time = tk.IntVar(value=15)
        self.water_time_box = tk.Spinbox(self.config_page, from_=0, to=1000, width=3, textvariable=self.water_time)
        self.air_time_label = tk.Label(self.config_page, text="Air time:", bg=self.label_bg_color)
        self.air_time = tk.IntVar(value=15)
        self.air_time_box = tk.Spinbox(self.config_page, from_=0, to=1000, width=3, textvariable=self.air_time)

        # Loop Volumes
        self.buffer_loop_vol_var = tk.DoubleVar()
        self.sample_loop_vol_var = tk.DoubleVar()
        self.buffer_loop_vol_var.set(0.140)
        self.sample_loop_vol_var.set(0.070)

        self.buffer_loop_label = tk.Label(self.config_page, text="Buffer loop Vol (ml): ", bg=self.label_bg_color)
        self.sample_loop_label = tk.Label(self.config_page, text="Sample loop Vol (ml): ", bg=self.label_bg_color)

        self.buffer_loop_entry = tk.Spinbox(self.config_page, from_=0, to=10, increment=0.01, width=4, textvariable=self.buffer_loop_vol_var)
        self.sample_loop_entry = tk.Spinbox(self.config_page, from_=0, to=10, increment=0.01, width=4, textvariable=self.sample_loop_vol_var)
        # Make Instrument
        self.AvailablePorts = []
        self.controller = SAXSDrivers.SAXSController(timeout=0.1)
        self.instruments = []
        self.pump = None
        self.cerberus_pump = None
        self.purge_valve = None
        self.NumberofPumps = 0
        self.last_delivered_volume = 0
        self.is_insert_purging = False
        self.is_insert_sheath_purging = False

        ### Setup Page ###
        self.hardware_config_options = ("Pump", "Oil Valve", "Sample/Buffer Valve", "Loading Valve", "Purge", "cerberus Oil", "cerberus Load", "cerberus Pump")
        self.setup_page_buttons = []
        self.setup_page_variables = []
        self.refresh_com_ports = tk.Button(self.setup_page, text="Refresh COM", command=lambda: self.refresh_com_list())
        self.AddPump = tk.Button(self.setup_page, text="Add Pump", command=lambda: self.add_pump_set_buttons())
        self.AddRheodyne = tk.Button(self.setup_page, text="Add Rheodyne", command=lambda: self.add_rheodyne_set_buttons())
        self.AddVICI = tk.Button(self.setup_page, text="Add VICI Valve", command=lambda: self.AddVICISetButtons())
        self.ControllerCOM = COMPortSelector.COMPortSelector(self.setup_page, exportselection=0, height=3)
        self.ControllerSet = tk.Button(self.setup_page, text="Set Microntroller", command=lambda: self.controller.set_port(self.AvailablePorts[int(self.ControllerCOM.curselection()[0])].device, self.instruments))
        self.I2CScanButton = tk.Button(self.setup_page, text="Scan I2C line", command=lambda: self.controller.scan_i2c())

        log_length = 25  # in lines
        self.user_logger_gui = ConsoleUi.ConsoleUi(self.user_logs, True)
        self.user_logger_gui.set_levels((logging.INFO, logging.WARNING))
        self.advanced_logger_gui = ConsoleUi.ConsoleUi(self.advanced_logs)
        self.draw_static()

        # brings in two queues to hold commands called from different pages
        # the threads are instantiated and exist in solocomm.py
        self.queue = solocomm.controlQueue # holds commands from Auto page
        self.manual_queue = solocomm.ManualControlQueue # from Manual page
        self.queue_busy = False
        self.listen_run_flag = threading.Event()
        self.listen_run_flag.set()
        self.start_control_thread()
        self.start_manual_thread()


    def draw_static(self):
        """Define the geometry of the frames and objects."""
        self.stop_button.grid(row=0, column=0, columnspan=2, rowspan=2, sticky='N')
        self.exit_button.grid(row=0, column=1, sticky='NE')
        self.core.grid(row=1, column=0)
        self.logs.grid(row=1, column=1)
        self.stop_button.lift()
        # Main Tab Bar
        self.core.add(self.auto_page, text='Auto')
        self.core.add(self.manual_page, text='Manual')
        self.core.add(self.config_page, text='Config')
        self.core.add(self.setup_page, text='Setup')
        # Log Tab Bar
        self.logs.add(self.user_logs, text='Simple')
        self.logs.add(self.advanced_logs, text='Advanced')
        # Auto Page Buttons
        self.run_buffer.grid(row=0, column=0, rowspan=2, padx=10)
        self.run_sample.grid(row=0, column=1, rowspan=2, padx=10)
            # second row
        self.run_pumps.grid(row=3, column=0, rowspan=2, padx=0, columnspan=2, pady=10)
        #self.pause_pump.grid(row=3, column=1, rowspan=2, padx=10, pady=10)
        self.remaining_buffer.grid(row=3, column=3, padx=10)
        self.remaining_sample.grid(row=4, column=3, padx=10)
        self.remaining_buffer_vol.grid(row=3, column=4)
        self.remaining_sample_vol.grid(row=4, column=4)

        self.oil_used_label.grid(row=5, column=3, padx=10)
        self.oil_used_vol.grid(row=5, column=4)
          # third row
        self.main_flowrate.grid(row=6, column=0, rowspan=2, padx=10)
        self.set_main_flowrate.grid(row=6, column=1, rowspan=2, padx=10)
            # fourth rowcounter
        self.clean_button.grid(row=9, column=0, rowspan=2, pady=10)
        self.refill_button.grid(row=9, column=1, rowspan=2, pady=10)
        self.load_buffer_button.grid(row=12, column=0, rowspan=2, padx=10)
        self.load_sample_button.grid(row=12, column=1, rowspan=2, padx=10)

        # Config Page
        self.loading_valve_names_label.grid(column=0, row=0, columnspan=6, sticky=tk.W)
        valverow=1
        self.loading_cell_label.grid(column=0, row=valverow)
        self.loading_cell_entry.grid(row=valverow, column=1)
        self.loading_load_label.grid(row=valverow, column=2)
        self.loading_load_entry.grid(row=valverow, column=3)
        self.loading_HSoap_label.grid(row=valverow, column=4)
        self.loading_HSoap_entry.grid(row=valverow, column=5)
        self.loading_LSoap_label.grid(row=valverow, column=6)
        self.loading_LSoap_entry.grid(row=valverow, column=7)
        self.loading_Water_label.grid(row=valverow, column=8)
        self.loading_Water_entry.grid(row=valverow, column=9)
        self.loading_Air_label.grid(row=valverow, column=10)
        self.loading_Air_entry.grid(row=valverow, column=11)
        valverow = 2
        self.cerberus_loading_valve_names_label.grid(row=valverow, column=0, columnspan=6, sticky=tk.W)
        valverow = 3
        self.cerberus_loading_cell_label.grid(column=0, row=valverow)
        self.cerberus_loading_cell_entry.grid(row=valverow, column=1)
        self.cerberus_loading_load_label.grid(row=valverow, column=2)
        self.cerberus_loading_load_entry.grid(row=valverow, column=3)
        self.cerberus_loading_HSoap_label.grid(row=valverow, column=4)
        self.cerberus_loading_HSoap_entry.grid(row=valverow, column=5)
        self.cerberus_loading_LSoap_label.grid(row=valverow, column=6)
        self.cerberus_loading_LSoap_entry.grid(row=valverow, column=7)
        self.cerberus_loading_Water_label.grid(row=valverow, column=8)
        self.cerberus_loading_Water_entry.grid(row=valverow, column=9)
        self.cerberus_loading_Air_label.grid(row=valverow, column=10)
        self.cerberus_loading_Air_entry.grid(row=valverow, column=11)
        valverow = 4
        self.oil_valve_names_label.grid(row=valverow, column=0, columnspan=6, sticky=tk.W)
        valverow = 5
        self.oil_pump_label.grid(row=valverow, column=0)
        self.oil_pump_entry.grid(row=valverow, column=1)
        self.oil_waste_label.grid(row=valverow, column=2)
        self.oil_waste_entry.grid(row=valverow, column=3)
        self.oil_insertpurge_label.grid(row=valverow, column=4)
        self.oil_insertpurge_entry.grid(row=valverow, column=5)
        valverow = 6
        self.coil_valve_names_label.grid(row=valverow, column=0, columnspan=6, sticky=tk.W)
        valverow = 7
        self.cerberus_oil_pump_label.grid(row=valverow, column=0)
        self.cerberus_oil_pump_entry.grid(row=valverow, column=1)
        self.cerberus_oil_waste_label.grid(row=valverow, column=2)
        self.cerberus_oil_waste_entry.grid(row=valverow, column=3)
        self.cerberus_oil_insertpurge_label.grid(row=valverow, column=4)
        self.cerberus_oil_insertpurge_entry.grid(row=valverow, column=5)
        # Cleaning Times
        valverow=8
        self.cleaning_config_label.grid(row=valverow, column=0, columnspan=3, sticky=tk.W)
        valverow=9
        self.low_soap_time_label.grid(row=valverow, column=0, sticky=tk.W+tk.E+tk.N+tk.S)
        self.low_soap_time_box.grid(row=valverow, column=1, sticky=tk.W+tk.E+tk.N+tk.S)
        self.high_soap_time_label.grid(row=valverow, column=2, sticky=tk.W+tk.E+tk.N+tk.S)
        self.high_soap_time_box.grid(row=valverow, column=3, sticky=tk.W+tk.E+tk.N+tk.S)
        self.water_time_label.grid(row=valverow, column=4, sticky=tk.W+tk.E+tk.N+tk.S)
        self.water_time_box.grid(row=valverow, column=5, sticky=tk.W+tk.E+tk.N+tk.S)
        self.air_time_label.grid(row=valverow, column=6, sticky=tk.W+tk.E+tk.N+tk.S)
        self.air_time_box.grid(row=valverow, column=7, sticky=tk.W+tk.E+tk.N+tk.S)
        valverow=10
        self.buffer_loop_label.grid(row=valverow, column=0, sticky=tk.W+tk.N)
        self.buffer_loop_entry.grid(row=valverow, column=1)
        valverow=11
        self.sample_loop_label.grid(row=valverow, column=0, sticky=tk.W+tk.N)
        self.sample_loop_entry.grid(row=valverow, column=1)
        #Purge possitions
        valverow=12
        self.purge_possition_label.grid(row=valverow, column=0, sticky=tk.W+tk.E+tk.N+tk.S)
        valverow=13
        self.purge_running_label.grid(row=valverow, column=0, sticky=tk.W+tk.E+tk.N+tk.S)
        self.purge_running_box.grid(row=valverow, column=1, sticky=tk.W+tk.E+tk.N+tk.S)
        self.purge_water_label.grid(row=valverow, column=2, sticky=tk.W+tk.E+tk.N+tk.S)
        self.purge_water_box.grid(row=valverow, column=3, sticky=tk.W+tk.E+tk.N+tk.S)
        self.purge_soap_label.grid(row=valverow, column=4, sticky=tk.W+tk.E+tk.N+tk.S)
        self.purge_soap_box.grid(row=valverow, column=5, sticky=tk.W+tk.E+tk.N+tk.S)
        self.purge_air_label.grid(row=valverow, column=6, sticky=tk.W+tk.E+tk.N+tk.S)
        self.purge_air_box.grid(row=valverow, column=7, sticky=tk.W+tk.E+tk.N+tk.S)
        # Setup page
        self.refresh_com_ports.grid(row=0, column=0)
        self.AddPump.grid(row=0, column=1)
        self.AddRheodyne.grid(row=0, column=2)
        self.AddVICI.grid(row=0, column=3)
        self.ControllerCOM.grid(row=1, column=0)
        self.ControllerSet.grid(row=1, column=2)
        self.I2CScanButton.grid(row=1, column=3)
        # self.refresh_com_list()
        # Create the default instruments
        self.add_pump_set_buttons(name="Top Pump")  # Pump 1  TODO: set address explicitly
        self.add_pump_set_buttons(name="Bottom Pump", address=1)  # Pump 2
        self.add_rheodyne_set_buttons(name="Loading", address=14)  # Loading valve 2
        self.add_rheodyne_set_buttons(name="Oil", address=8)  # Oil Valve
        self.AddVICISetButtons(name="Sample", address="1")    # Sample Valve
        self.add_rheodyne_set_buttons(name="Ceberus Loading", address=24)  # Cerberus Loading
        self.add_rheodyne_set_buttons(name="Cerberus Oil", address=20)  # Cerberus Oil
        self.AddVICISetButtons(name="Ligand", address="2", silent=True)     # Cerberus Sample
        self.add_rheodyne_set_buttons(name="Purge")   # Purge
        # done creating
        # Now Create main objects to assign these objects
        self.pump = self.instruments[0]
        self.cerberus_pump = self.instruments[1]

        self.loading_valve = self.instruments[2]
        self.oil_valve = self.instruments[3]
        self.sample_valve = self.instruments[4]

        self.cerberus_loading_valve = self.instruments[5]
        self.cerberus_oil_valve = self.instruments[6]
        self.ligand_valve = self.instruments[7]

        self.purge_valve = self.instruments[8]

        # Now loggers
        self.python_logger.setLevel(logging.DEBUG)
        self.user_logger_gui.pass_logger(self.python_logger)
        self.advanced_logger_gui.pass_logger(self.python_logger)
        # self.python_logger.addHandler(file_handler)  # logging to a file
        self.controller.logger = self.python_logger  # Pass the logger to the controller

        # Manual Pqage Purge adding
        self.purge_button.grid(row=99, column=0, columnspan=12,rowspan=1, sticky=tk.N+tk.S)
        self.purge_soap_button.grid(row=100, column=0, columnspan=6, sticky=tk.W+tk.E+tk.N+tk.S)
        self.purge_dry_button.grid(row=100, column=6, columnspan=6 ,sticky=tk.W+tk.E+tk.N+tk.S)
        self.purge_insert_soap_button.grid(row=101, column=0, columnspan=6, sticky=tk.W+tk.E+tk.N+tk.S)
        self.purge_insert_water_button.grid(row=101, column=6, columnspan=6, sticky=tk.W+tk.E+tk.N+tk.S)
        self.purge_sheath_insert_soap_button.grid(row=102, column=0, columnspan=6, sticky=tk.W+tk.E+tk.N+tk.S)
        self.purge_sheath_insert_water_button.grid(row=102, column=6, columnspan=6, sticky=tk.W+tk.E+tk.N+tk.S)



    def stop(self):
        """Stop all running widgets."""
        self.control_thread.abortProcess = True
        # TODO: abort manual thread
        self.stop_instruments()

    def stop_instruments(self):
        SAXSDrivers.InstrumentTerminateFunction(self.instruments)

    def start_control_thread(self):
        """ Creates the thread for running instruments from auto thread"""
        self.control_thread = solocomm.ControlThread(self)
        self.control_thread.daemon = True
        self.control_thread.start()

    def start_manual_thread(self):
        """ Creates the thread for running instruments SEPARATE from auto thread"""
        # FIXME: doesn't attribute manual thread to Main, change this or fix the control thread
        manual_thread = solocomm.ManualControlThread(self)
        manual_thread.daemon = True
        manual_thread.start()

    def handle_exception(self, exception, value, traceback):
        """Add python exceptions to the GUI log."""
        self.python_logger.exception("Caught exception:")

    def exit_(self):
        """Exit the GUI and stop all running things."""
        if self.listen_run_flag.is_set():
            self.listen_run_flag.clear() # kills the control threads
        print("WAITING FOR OTHER THREADS TO SHUT DOWN...")
        print(threading.enumerate())

        print("THANK Y'ALL FOR COMING! A LA PROCHAINE !")
        self.main_window.destroy()


    # FIXME: does the following function even get used?
    def cerberus_clean_and_refill_command(self, vol_flag=True):
        if vol_flag:
            vol=self.cerberus_volume.get()/1000
        else:
            vol = self.last_delivered_volume
        if vol == 0:
            vol=self.cerberus_volume.get()/1000
        """Clean the buffer and sample loops, then refill the oil."""
        # elveflow_oil_channel = int(self.elveflow_oil_channel.get())  # throws an error if the conversion doesn't work
        # elveflow_oil_pressure = self.elveflow_oil_pressure.get()

        self.queue.put((self.python_logger.info, "Starting to run clean/refill command"))
        self.flowpath.set_unlock_state(False)
        # self.queue.put((self.elveflow_display.pressureValue_var[elveflow_oil_channel - 1].set, elveflow_oil_pressure))  # Set oil pressure
        # self.queue.put((self.elveflow_display.start_pressure, elveflow_oil_channel))

        self.queue.put(self.cerberus_pump.stop_pump)
        self.queue.put((self.pump.refill_volume, (self.sample_volume.get()+self.first_buffer_volume.get()+self.last_buffer_volume.get())/1000, self.oil_refill_flowrate.get()))
        self.queue.put((self.cerberus_pump.refill_volume, vol, self.cerberus_refill_rate.get()))

        self.clean_only_command()

        self.queue.put((self.pump.wait_until_stopped, 120))
        self.queue.put((self.cerberus_pump.wait_until_stopped, 120))
        self.queue.put(self.pump.infuse)
        self.queue.put(self.cerberus_pump.infuse)
        # self.queue.put((self.elveflow_display.pressureValue_var[elveflow_oil_channel - 1].set, "0"))  # Set oil pressure to 0
        # self.queue.put((self.elveflow_display.start_pressure, elveflow_oil_channel))

        self.queue.put((self.python_logger.info, 'Clean and refill done. 完成了！'))
        self.queue.put(self.set_refill_flag_true)
        self.queue.put(self.play_done_sound)

    def refill_only_command(self):
        MsgBox = messagebox.askquestion('Warning', 'Please set elveflow Ch4 pressure to 8000bar ?', icon='warning')
        if MsgBox == 'yes':
            pass
        else:
            return
        self.queue.put((self.python_logger.info, "Refilling pumps"))
        self.queue.put((self.pump.refill_volume, self.oil_used, self.refill_rate ))
        self.queue.put((self.cerberus_pump.refill_volume, self.oil_used, self.refill_rate ))
        self.clean_only_command()
        self.queue.put((self.pump.wait_until_stopped, 120))
        self.queue.put((self.cerberus_pump.wait_until_stopped, 120))
        self.queue.put(self.pump.infuse)
        self.queue.put(self.cerberus_pump.infuse)
        self.queue.put(self.reset_oil_vol)
        self.queue.put((self.python_logger.info, "Done refilling pumps"))
        self.queue.put(self.elveflow_reminder)

    def elveflow_reminder(self):
        MsgBox = messagebox.askquestion('Warning', 'Please set elveflow Ch4 pressure to 0', icon='warning')
        if MsgBox == 'yes':
            pass
        else:
            return

    def reset_oil_vol(self):
        self.oil_used = 0.0
        self.oil_used_var.set(self.oil_used)

    def set_refill_flag_true(self):
        """def this_this_dumb - This function is so that the flag setting is done in the queue.
        This way it if it fails the flag isn't reset"""
        self.oil_refill_flag = True

    def clean_only_command(self):
        """Clean the buffer and sample loops."""
        self.queue.put((self.python_logger.info, "Starting Cleaning"))
        self.clean_loop(0)
        self.clean_loop(1)
        self.load_buffer_command()
        self.queue.put(self.reset_delivered_vol)
        self.queue.put((self.python_logger.info, "Both Loops Cleaned"))

    def clean_loop(self, loop):
        """ This is the main function to clean different loops"""
        self.queue.put((self.python_logger.info, "Starting to clean buffer"))
        self.queue.put((self.oil_valve.switchvalve, self.oil_waste_var.get()))
        self.queue.put((self.sample_valve.switchvalve, loop))
        self.queue.put((self.loading_valve.switchvalve, self.loading_HSoap_var.get()))
        self.queue.put((time.sleep, self.high_soap_time.get()))
        self.queue.put((self.loading_valve.switchvalve, self.loading_Water_var.get()))  # to avoid passing oil
        self.queue.put((self.loading_valve.switchvalve, self.loading_load_var.get()))

        self.queue.put((self.python_logger.info, "Cleaning cerberus"))
        self.queue.put((self.cerberus_oil_valve.switchvalve, self.cerberus_oil_waste_var.get()))
        self.queue.put((self.ligand_valve.switchvalve, loop))
        self.queue.put((self.cerberus_loading_valve.switchvalve, self.cerberus_loading_HSoap_var.get()))
        self.queue.put((time.sleep, self.high_soap_time.get()))

        self.queue.put((self.python_logger.info, "Flushing High Flow Soap"))
        self.queue.put((self.cerberus_oil_valve.switchvalve, self.cerberus_oil_waste_var.get()))
        self.queue.put((self.ligand_valve.switchvalve, loop))
        self.queue.put((self.cerberus_loading_valve.switchvalve, self.cerberus_loading_LSoap_var.get()))
        self.queue.put((self.oil_valve.switchvalve, self.oil_waste_var.get()))
        self.queue.put((self.sample_valve.switchvalve, loop))
        self.queue.put((self.loading_valve.switchvalve, self.loading_LSoap_var.get()))
        self.queue.put((time.sleep, self.low_soap_time.get()))

        self.queue.put((self.python_logger.info, "Flushing Water"))
        self.queue.put((self.cerberus_oil_valve.switchvalve, self.cerberus_oil_waste_var.get()))
        self.queue.put((self.ligand_valve.switchvalve, loop))
        self.queue.put((self.cerberus_loading_valve.switchvalve, self.cerberus_loading_Water_var.get()))
        self.queue.put((self.oil_valve.switchvalve, self.oil_waste_var.get()))
        self.queue.put((self.sample_valve.switchvalve, loop))
        self.queue.put((self.loading_valve.switchvalve, self.loading_Water_var.get()))
        self.queue.put((time.sleep, self.water_time.get()))

        self.queue.put((self.python_logger.info, "Air drying 1"))
        self.queue.put((self.cerberus_oil_valve.switchvalve, self.cerberus_oil_waste_var.get()))
        self.queue.put((self.ligand_valve.switchvalve, loop))
        self.queue.put((self.cerberus_loading_valve.switchvalve, self.cerberus_loading_Air_var.get()))
        self.queue.put((time.sleep, self.air_time.get()))
        self.queue.put((self.cerberus_loading_valve.switchvalve, self.cerberus_loading_Water_var.get()))
        self.queue.put((self.cerberus_loading_valve.switchvalve, self.cerberus_loading_load_var.get()))

        self.queue.put((self.python_logger.info, "Air drying 2"))
        self.queue.put((self.oil_valve.switchvalve, self.oil_waste_var.get()))
        self.queue.put((self.sample_valve.switchvalve, loop))
        self.queue.put((self.loading_valve.switchvalve, self.loading_Air_var.get()))
        self.queue.put((time.sleep, self.air_time.get()))
        self.queue.put((self.loading_valve.switchvalve, self.loading_load_var.get()))


        self.queue.put((self.python_logger.info, "Done Cleaning Loop: "+str(loop+1)))

    def load_sample_command(self):
        self.load_loop(1)

    def load_loop(self, loop):
        self.queue.put((self.loading_valve.switchvalve, self.loading_load_var.get()))
        self.queue.put((self.oil_valve.switchvalve, self.oil_waste_var.get()))
        self.queue.put((self.sample_valve.switchvalve, loop))
        self.queue.put((self.cerberus_loading_valve.switchvalve, self.cerberus_loading_load_var.get()))
        self.queue.put((self.cerberus_oil_valve.switchvalve, self.cerberus_oil_waste_var.get()))
        self.queue.put((self.ligand_valve.switchvalve, loop))

        """
        self.queue.put((self.set_insert_purge, False))
        self.queue.put((self.set_insert_sheath_purge, False))
        self.queue.put(self.unset_insert_purge)
        self.queue.put(self.unset_insert_sheath_purge)
        """

    def load_buffer_command(self):
        self.load_loop(0)

    def run_pumps_button_command(self):
        """Processes a press of the "Run Pumps" from the Auto page.

        If the pumps are stopped, then they will start in whichever position
        the setup is currently set to (sample or buffer). Before running, the
        setup will update according to the Config page, as if the "Set [position]"
        button was pressed for the position. No position, or more broadly
        an invalid position, will log that the command was ignored.

        If they are currently running, the pumps will actually stop.
        """
        if not self.pumps_running_bool:
            if self.running_pos == "sample":
                self.run_sample_command()
                self.start_both_pumps(self.remaining_sample_real, self.auto_flowrate_variable.get())
            elif self.running_pos== "buffer":
                self.run_buffer_command()
                self.start_both_pumps(self.remaining_buffer_real, self.auto_flowrate_variable.get())
            else:
                self.python_logger.info("No running path set. Command Ignored.")
                return
        else:
            self.stop_both_pumps()

        self.queue.put(self.toggle_running)

    def start_both_pumps(self, vol, rt):
        # Set Pump settings
        self.queue.put((self.pump.infuse_volume, vol, rt))
        self.queue.put((self.cerberus_pump.infuse_volume, vol, rt))
        # Start Pumps
        self.queue.put(self.pump.start_pump)
        self.queue.put(self.cerberus_pump.start_pump)


    def stop_both_pumps(self):
        self.queue.put(self.pump.stop) # TODO: check if all pumps stop on command

    def update_delivered_vol(self):
        pump1vol = float(self.pump.get_delivered_volume())
        pump2vol = float(self.cerberus_pump.get_delivered_volume())
        if pump1vol > pump2vol:
            self.oil_used += pump1vol
            if self.running_pos == "buffer":
                self.remaining_buffer_real = round(self.remaining_buffer_real-pump1vol,5)
                self.remaining_buffer_vol_var.set(self.remaining_buffer_real)
            elif self.running_pos == "sample":
                self.remaining_sample_real = round(self.remaining_sample_real-pump1vol,5)
                self.remaining_sample_vol_var.set(self.remaining_sample_real)
        else:
            self.oil_used += pump2vol
            if self.running_pos == "buffer":
                self.remaining_buffer_real = round(self.remaining_buffer_real-pump2vol,5)
                self.remaining_buffer_vol_var.set(self.remaining_buffer_real)
            elif self.running_pos == "sample":
                self.remaining_sample_real = round(self.remaining_sample_real-pump2vol,5)
                self.remaining_sample_vol_var.set(self.remaining_sample_real)
        self.oil_used_var.set(round(self.oil_used, 5))

    def reset_delivered_vol(self):
        self.remaining_buffer_real = self.buffer_loop_vol_var.get()
        self.remaining_sample_real = self.sample_loop_vol_var.get()
        self.remaining_buffer_vol_var.set(self.remaining_buffer_real)
        self.remaining_sample_vol_var.set(self.remaining_sample_real)

    def toggle_running(self):
        self.pumps_running_bool = not self.pumps_running_bool
        if self.pumps_running_bool:
            bgcolor = "green"
            pump_text = "Running"
            self.volume_count_down()
        else:
            bgcolor = "red"
            pump_text = "Stopped"
            self.update_delivered_vol()
        self.run_pumps.config(bg=bgcolor, text=pump_text)



    def run_buffer_command(self):
        self.queue.put((self.loading_valve.switchvalve, self.loading_cell_var.get()))
        self.queue.put((self.oil_valve.switchvalve, self.oil_pump_var.get()))
        self.queue.put((self.sample_valve.switchvalve, 0))
        self.queue.put((self.cerberus_loading_valve.switchvalve, self.cerberus_loading_cell_var.get()))
        self.queue.put((self.cerberus_oil_valve.switchvalve, self.cerberus_oil_pump_var.get()))
        self.queue.put((self.ligand_valve.switchvalve, 0))
        self.queue.put(self.toggle_to_buffer)
        # change valve possitions
    def toggle_to_buffer(self):
        self.run_buffer.config(bg="green", fg="white")
        self.run_sample.config(bg="white", fg="black")
        self.running_pos = "buffer"

    def run_sample_command(self):
        self.queue.put((self.loading_valve.switchvalve, self.loading_cell_var.get()))
        self.queue.put((self.oil_valve.switchvalve, self.oil_pump_var.get()))
        self.queue.put((self.sample_valve.switchvalve, 1))
        self.queue.put((self.cerberus_loading_valve.switchvalve, self.cerberus_loading_cell_var.get()))
        self.queue.put((self.cerberus_oil_valve.switchvalve, self.cerberus_oil_pump_var.get()))
        self.queue.put((self.ligand_valve.switchvalve, 1))
        self.queue.put(self.toggle_to_sample)

        # change valve possitions
    def toggle_to_sample(self):
        self.run_sample.config(bg="green", fg="white")
        self.run_buffer.config(bg="white", fg="black")
        self.running_pos = "sample"

    def set_auto_flowrate_command(self):
        rt = self.auto_flowrate_variable.get()
        self.queue.put((self.pump.set_infuse_rate, rt))
        self.queue.put((self.cerberus_pump.set_infuse_rate, rt))

    def unset_purge(self):
        self.purge_valve.switchvalve(self.purge_running_pos.get())
        self.purge_button.configure(bg="white smoke")
        self.purge_soap_button.configure(bg="white smoke")

        self.purge_dry_button.configure(bg="white smoke")

    def purge_command(self):
        run_position = self.purge_running_pos.get()
        purge_position = self.purge_water_pos.get()
        if self.purge_valve.position == purge_position:
            self.manual_queue.put((self.purge_valve.switchvalve, run_position))
            self.manual_queue.put(lambda: self.purge_button.configure(bg="white smoke"))
            self.manual_queue.put((self.python_logger.info, "Purge stopped"))
        else:
            self.manual_queue.put((self.purge_valve.switchvalve, purge_position))
            self.manual_queue.put(lambda: self.purge_button.configure(bg="green"))
            self.manual_queue.put(lambda: self.purge_soap_button.configure(bg="white smoke"))
            self.manual_queue.put(lambda: self.purge_dry_button.configure(bg="white smoke"))
            self.manual_queue.put((self.python_logger.info, "Purging"))

    def purge_soap_command(self):
        run_position = self.purge_running_pos.get()
        purge_position = self.purge_soap_pos.get()
        if self.purge_valve.position == purge_position:
            self.manual_queue.put((self.purge_valve.switchvalve, run_position))
            self.manual_queue.put(lambda: self.purge_soap_button.configure(bg="white smoke"))
            self.manual_queue.put((self.python_logger.info, "Purge stopped"))
        else:
            self.manual_queue.put((self.purge_valve.switchvalve, purge_position))
            self.manual_queue.put(lambda: self.purge_soap_button.configure(bg="green"))
            self.manual_queue.put(lambda: self.purge_button.configure(bg="white smoke"))
            self.manual_queue.put(lambda: self.purge_dry_button.configure(bg="white smoke"))
            self.manual_queue.put((self.python_logger.info, "Purging soap"))

    def purge_dry_command(self):
        run_position = self.purge_running_pos.get()
        purge_position = self.purge_air_pos.get()
        if self.purge_valve.position == purge_position:
            self.manual_queue.put((self.purge_valve.switchvalve, run_position))
            self.manual_queue.put(lambda: self.purge_dry_button.configure(bg="white smoke"))
            self.manual_queue.put((self.python_logger.info, "Purge stopped"))
        else:
            self.manual_queue.put((self.purge_valve.switchvalve, purge_position))
            self.manual_queue.put(lambda: self.purge_dry_button.configure(bg="green"))
            self.manual_queue.put(lambda: self.purge_soap_button.configure(bg="white smoke"))
            self.manual_queue.put(lambda: self.purge_button.configure(bg="white smoke"))
            self.manual_queue.put((self.python_logger.info, "Purging soap"))


    def unset_insert_purge(self, reset=True):
        self.purge_insert_soap_button.configure(bg="white smoke")
        self.purge_insert_water_button.configure(bg="white smoke")
        #self.is_insert_purging = False

    def unset_insert_sheath_purge(self):
        self.purge_sheath_insert_soap_button.configure(bg="white smoke")
        self.purge_sheath_insert_water_button.configure(bg="white smoke")
        #self.is_insert_sheath_purging = False

    def set_insert_purge(self, option=True):
        self.is_insert_purging = option

    def set_insert_sheath_purge(self, option=True):
        self.is_insert_sheath_purging = option

    def insert_purge(self, fluid=""):
        self.unset_insert_purge()
        pos=self.oil_insertpurge_var.get()
        if not self.is_insert_purging:
            self.queue.put((self.python_logger.info, "Purgin insert with "+fluid))
            self.queue.put((self.loading_valve.switchvalve, self.loading_cell_var.get()))
            self.queue.put((self.sample_valve.switchvalve, 0))
            self.queue.put((self.oil_valve.switchvalve, pos))
            if fluid == "Soap":
                self.queue.put(lambda: self.purge_insert_soap_button.configure(bg="green"))
            elif fluid == "Water":
                self.queue.put(lambda: self.purge_insert_water_button.configure(bg="green"))
            self.queue.put((self.set_insert_purge, True))
        else:
            self.queue.put(self.load_buffer_command)
            self.queue.put((self.set_insert_purge, False))
            pass

    def insert_sheath_purge(self, fluid=""):
        self.unset_insert_sheath_purge()
        pos=self.cerberus_oil_insertpurge_var.get()

        if not self.is_insert_sheath_purging:
            self.queue.put((self.python_logger.info, "Purgin insert with "+fluid))
            self.queue.put((self.cerberus_loading_valve.switchvalve, self.cerberus_loading_cell_var.get()))
            self.queue.put((self.cerberus_oil_valve.switchvalve, pos))
            if fluid == "Soap":
                self.queue.put(lambda: self.purge_sheath_insert_soap_button.configure(bg="green"))
            elif fluid == "Water":
                self.queue.put(lambda: self.purge_sheath_insert_water_button.configure(bg="green"))
            self.queue.put((self.set_insert_sheath_purge, True))
        else:
            self.queue.put(self.load_buffer_command)
            self.queue.put((self.set_insert_sheath_purge, False))
            pass

    def toggle_buttons(self):
        buttons = (self.run_buffer, self.run_sample, self.load_buffer_button, self.load_sample_button, self.clean_button, self.refill_button)

        if self.queue_busy or self.pumps_running_bool:
            for button in buttons:
                button['state'] = 'disabled'
        else:
            for button in buttons:
                button['state'] = 'normal'

    def play_done_sound(self):
        possible_songs = [
            [(392, 300),(494, 300),(587, 300),(740, 300),(783, 600)], # major 7 arpeggio
            [(330, 250),(440, 750),(554, 250),(659, 750),(440, 250),(415, 750),(554, 250),(659, 750)], # 月亮代表我的心
            [(659, 150),(659, 300),(659, 300),(523, 150),(659, 300),(784, 600),(392, 600)], # Mario
            [(784, 150),(740, 150),(622, 150),(440, 150),(415, 150),(659, 150),(831, 150),(1047, 150)], # Zelda
            [(880, 400),(784, 200),(698, 400),(784, 200),(880, 400),(932, 200),(1047, 600),(880, 200),(784, 200),(698, 200),(659, 400),(587, 200),(659, 400),(698, 200),(523, 600)], # Do You Hear the People Sing?
            [(523, 200),(659, 400),(659, 200),(659, 200),(587, 200),(659, 200),(698, 600),(659, 400),(659, 200),(587, 400),(587, 200),(587, 200),(523, 200),(587, 200),(659, 600),(523, 600)], # For He's a Jolly Good Fellow
            [(415, 150),(311, 150),(415, 150),(523, 150),(415, 150),(523, 150),(622, 450),(523, 300),(415, 150),(554, 450),(523, 300),(466, 150),(415, 450),(466, 450),(415, 450)], # Kid Icarus Underworld
            [(831, 600),(932, 200),(1047, 600),(932, 200),(831, 400),(698, 400),(698, 400),(622, 400)], # Cornell Alma Mater
            [(392, 200),(523, 200),(523, 100),(523, 100),(523, 200),(659, 200),(784, 200),(659, 200),(523, 400)], #Wheels on the Bus
            [(466, 300),(622, 600),(784, 150),(622, 150),(784, 600),(698, 300),(622, 600),(523, 300),(466, 600)], # Amazing Grace
            [(392, 100),(440, 100),(494, 200),(587, 200),(587, 300),(659, 100),(587, 200),(494, 200),(392, 300)], # Oh Susanna
            [(523, 200),(622, 100),(523, 200),(932, 300),(831, 200),(784, 100),(831, 200),(932, 500)], # Jump Up Superstar!
            [(659, 200),(622, 200),(659, 200),(622, 200),(659, 200),(494, 200),(587, 200),(523, 200),(440, 500)], # Für Elise
            [(440, 400),(587, 200),(740, 200),(740, 400),(494, 400),(494, 400),(554, 133),(587, 133),(659, 133),(587, 400),(554, 400)], # Fire Emblem
            [(587, 200),(659, 200),(698, 200),(784, 200),(659, 400),(523, 200),(587, 500)], # The Lick
            [(740, 400),(1109, 200),(932, 200),(932, 400),(831, 200),(740, 200),(740, 200),(988, 400),(932, 200),(932, 200),(831, 200),(831, 200),(740, 200)], # All Star
            [(466, 100),(523, 100),(554, 100),(466, 100),(698, 400),(698, 200),(622, 600),(415, 100),(466, 100),(523, 100),(415, 100),(622, 400),(622, 200),(554, 600)], # Never Gonna Give You Up
            [(740, 200),(659, 200),(587, 200),(554, 200),(587, 200),(659, 200),(587, 200),(440, 200),(370, 200),(392, 200),(440, 200),(494, 200),(440, 200),(370, 200),(440, 400)], # Turkey in the Straw
            [(494, 125),(440, 125),(415, 125),(440, 125),(523, 500),(587, 125),(523, 125),(494, 125),(523, 125),(659, 500)], # Rondo Alla Turca
            [(294, 100),(294, 100),(587, 200),(440, 400),(415, 200),(392, 200),(349, 200),(294, 100),(349, 100),(392, 300)], # Megalovania
            [(932, 900),(831, 150),(740, 150),(831, 150),(740, 150),(831, 150),(740, 150),(698, 225),(622, 225),(587, 225),(554, 600)], # Rhapsody in Blue
            [(349, 200),(392, 400),(440, 400),(587, 400),(523, 600),(440, 400),(392, 200),(349, 200),(349, 200),], # McDonald's
            [(440, 300),(554, 300),(659, 200),(831, 400),(880, 400),(1175, 300),(1109, 300),(988, 200),(1109, 600),], # State Farm
            [(349, 200),(587, 200),(587, 100),(622, 100),(587, 100),(523, 100),(466, 200),(392, 200),(349, 200),(392, 200),(523, 200),(440, 200),(466, 400),], # We Wish You a Merry Christmas
            [(698, 300),(784, 300),(698, 150),(587, 150),(466, 300),(523, 300),(587, 300),(523, 150),(466, 150),(392, 300),(349, 600),], # Sleigh Ride
        ]
        notes = random.choice(possible_songs)
        for (note, duration) in notes:
            winsound.Beep(note,duration)

    def configure_to_hardware(self, keyword, instrument_index):
        """Assign an instrument to the software version of it."""
        # TODO: Add checks for value type
        if keyword == self.hardware_config_options[0]:
            if self.instruments[instrument_index].instrument_type == "Pump":
                self.pump = self.instruments[instrument_index]
                self.python_logger.info("Pump configured to FlowPath")
            else:
                self.python_logger.info("Invalid configuration for type " + self.instruments[instrument_index].instrument_type)
        elif keyword == self.hardware_config_options[1]:
            if self.instruments[instrument_index].instrument_type == "Rheodyne":
                self.flowpath.valve2.hardware = self.instruments[instrument_index]
                self.python_logger.info("Oil valve configured to FlowPath")
            else:
                self.python_logger.info("Invalid configuration for type: " + self.instruments[instrument_index].instrument_type)
        elif keyword == self.hardware_config_options[2]:
            if self.instruments[instrument_index].instrument_type == "VICI":
                self.flowpath.valve3.hardware = self.instruments[instrument_index]
                self.python_logger.info("Sample/Buffer valve configured to FlowPath")
            else:
                self.python_logger.info("Invalid configuration for type: " + self.instruments[instrument_index].instrument_type)
        elif keyword == self.hardware_config_options[3]:
            if self.instruments[instrument_index].instrument_type == "Rheodyne":
                self.flowpath.valve4.hardware = self.instruments[instrument_index]
                self.python_logger.info("Loading valve configerd to FlowPath")
            else:
                self.python_logger.info("Invalid configuration for type: " + self.instruments[instrument_index].instrument_type)
        elif keyword == self.hardware_config_options[4]:
            if self.instruments[instrument_index].instrument_type == "Rheodyne":
                self.purge_valve = self.instruments[instrument_index]
                self.python_logger.info("Purge valve configured to FlowPath")
            else:
                self.python_logger.info("Invalid configuration for type: " + self.instruments[instrument_index].instrument_type)
        elif keyword == self.hardware_config_options[5]:
            if self.instruments[instrument_index].instrument_type == "Rheodyne":
                self.flowpath.valve6.hardware = self.instruments[instrument_index]
                self.python_logger.info("cerberus Loading valve configerd to FlowPath")
            else:
                self.python_logger.info("Invalid configuration for type: " + self.instruments[instrument_index].instrument_type)
        elif keyword == self.hardware_config_options[6]:
            if self.instruments[instrument_index].instrument_type == "Rheodyne":
                self.flowpath.valve8.hardware = self.instruments[instrument_index]
                self.python_logger.info("cerberus Oil valve configured to FlowPath")
            else:
                self.python_logger.info("Invalid configuration for type: " + self.instruments[instrument_index].instrument_type)
        elif keyword == self.hardware_config_options[7]:
            if self.instruments[instrument_index].instrument_type == "Pump":
                self.cerberus_pump = self.instruments[instrument_index]
                self.python_logger.info("cerberus Pump configured to FlowPath")
            else:
                self.python_logger.info("Invalid configuration for type " + self.instruments[instrument_index].instrument_type)
        else:
            raise ValueError
        self.instruments[instrument_index].hardware_configuration = keyword

    def add_pump_set_buttons(self, address=0, name="Pump", hardware="", pc_connect=True):
        """Add pump buttons to the setup page."""
        self.instruments.append(SAXSDrivers.HPump(logger=self.python_logger, name=name, address=address, hardware_configuration=hardware, lock=self._lock, pc_connect=pc_connect))
        self.NumberofPumps += 1
        instrument_index = len(self.instruments)-1
        self.python_logger.info("Added pump")
        newvars = [tk.IntVar(value=address), tk.StringVar(value=name), tk.StringVar(value=hardware)]
        self.setup_page_variables.append(newvars)

        newbuttons = [
         COMPortSelector.COMPortSelector(self.setup_page, exportselection=0, height=4),
         tk.Button(self.setup_page, text="Set Port", command=lambda: self.instruments[instrument_index].set_port(self.AvailablePorts[int(self.setup_page_buttons[instrument_index][0].curselection()[0])].device)),
         tk.Button(self.setup_page, text="Send to Controller", command=lambda: self.instruments[instrument_index].set_to_controller(self.controller)),
         tk.Label(self.setup_page, text="   Pump Address:", bg=self.label_bg_color),
         tk.Spinbox(self.setup_page, from_=0, to=100, textvariable=self.setup_page_variables[instrument_index][0], width=6),
         tk.Label(self.setup_page, text="   Pump Name:", bg=self.label_bg_color),
         tk.Entry(self.setup_page, textvariable=self.setup_page_variables[instrument_index][1], width=10),
         tk.Button(self.setup_page, text="Set values", command=lambda: self.instrument_change_values(instrument_index))
         ]

        # Pumps share a port-> Dont need extra ones
        if self.NumberofPumps > 1:
            newbuttons[0] = tk.Label(self.setup_page, text="", bg=self.label_bg_color)
            #newbuttons[1] = tk.Label(self.setup_page, text="", bg=self.label_bg_color)
            #newbuttons[2] = tk.Label(self.setup_page, text="", bg=self.label_bg_color)

        self.setup_page_buttons.append(newbuttons)
        for i in range(len(self.setup_page_buttons)):
            for y in range(len(self.setup_page_buttons[i])):
                self.setup_page_buttons[i][y].grid(row=i+2, column=y, sticky=tk.W+tk.E)
        #self.refresh_com_list()
        self.add_pump_control_buttons()
        if hardware != "":
            self.configure_to_hardware(hardware, instrument_index)

    def refresh_dropdown(self, option_menu_list, options_to_put, VariableLocation):
        # Update Values in Config Selector
        for i in range(6):
            m = option_menu_list[i].children['menu']
            m.delete(0, tk.END)
            m.add_command(label="", command=lambda var=VariableLocation[i], val="": var.set(val))  # Add option to leave empty
            for name in options_to_put:
                if not name == "":
                    m.add_command(label=name, command=lambda var=VariableLocation[i], val=name: var.set(val))

    def instrument_change_values(self, instrument_index, isvalve=False):
        self.instruments[instrument_index].change_values(int((self.setup_page_variables[instrument_index][0]).get()), (self.setup_page_variables[instrument_index][1]).get())
        self.manual_page_variables[instrument_index][0].set(self.instruments[instrument_index].name+":  ")
        if isvalve:
            self.manual_page_buttons[instrument_index][2].config(to=self.setup_page_variables[instrument_index][2].get())
        # self.refresh_dropdown()

    def add_pump_control_buttons(self):
        instrument_index = len(self.instruments)-1
        newvars = [tk.StringVar(), tk.DoubleVar(value=0), tk.DoubleVar(value=0), tk.DoubleVar(value=0)]
        newvars[0].set(self.instruments[instrument_index].name+":  ")
        self.manual_page_variables.append(newvars)
        newbuttons = [
         tk.Label(self.manual_page, textvariable=self.manual_page_variables[instrument_index][0], bg=self.label_bg_color, font=self.manual_button_font),
         tk.Button(self.manual_page, text="Run", command=lambda: self.manual_queue.put(self.instruments[instrument_index].start_pump), width=6, font=self.manual_button_font),
         tk.Button(self.manual_page, text="Stop", command=lambda:self.manual_queue.put(self.instruments[instrument_index].stop_pump), width=6, font=self.manual_button_font),
         tk.Label(self.manual_page, text="  Infuse Rate:", bg=self.label_bg_color, font=self.manual_button_font),
         tk.Spinbox(self.manual_page, from_=0, to=1000, textvariable=self.manual_page_variables[instrument_index][1], width=4, font=self.manual_button_font),
         tk.Button(self.manual_page, text="Set", command=lambda: self.manual_queue.put((self.instruments[instrument_index].set_infuse_rate, self.manual_page_variables[instrument_index][1].get())), font=self.manual_button_font),
         tk.Label(self.manual_page, text="  Refill Rate:", bg=self.label_bg_color, font=self.manual_button_font),
         tk.Spinbox(self.manual_page, from_=0, to=1000, textvariable=self.manual_page_variables[instrument_index][2], width=4, font=self.manual_button_font),
         tk.Button(self.manual_page, text="Set", command=lambda: self.manual_queue.put((self.instruments[instrument_index].set_refill_rate, self.manual_page_variables[instrument_index][2].get())), font=self.manual_button_font),
         tk.Label(self.manual_page, text="  Direction:", bg=self.label_bg_color, font=self.manual_button_font),
         tk.Button(self.manual_page, text="Infuse", command=lambda: self.manual_queue.put(self.instruments[instrument_index].infuse), font=self.manual_button_font),
         tk.Button(self.manual_page, text="Refill", command=lambda: self.manual_queue.put(self.instruments[instrument_index].refill), font=self.manual_button_font),
         tk.Label(self.manual_page, text="Mode", bg=self.label_bg_color, font=self.manual_button_font),
         tk.Button(self.manual_page, text="Pump", command=lambda: self.manual_queue.put(self.instruments[instrument_index].set_mode_pump), font=self.manual_button_font),
         tk.Button(self.manual_page, text="Vol", command=lambda: self.manual_queue.put(self.instruments[instrument_index].set_mode_vol), font=self.manual_button_font),
         tk.Label(self.manual_page, text="  Target Vol (ml):", bg=self.label_bg_color, width=4, font=self.manual_button_font),
         tk.Spinbox(self.manual_page, from_=0, to=1000, textvariable=self.manual_page_variables[instrument_index][3], font=self.manual_button_font),
         # tk.Button(self.manual_page, text="Set", command=lambda: self.queue.put((self.instruments[instrument_index].set_target_vol, self.manual_page_variables[instrument_index][3].get())))
         tk.Button(self.manual_page, text="Set", command=lambda: self.manual_queue.put((self.instruments[instrument_index].set_target_vol, self.manual_page_variables[instrument_index][3].get())), font=self.manual_button_font)
         ]
        # Bind Enter to Spinboxes
        newbuttons[4].bind('<Return>', lambda event: self.manual_queue.put((self.instruments[instrument_index].set_infuse_rate, self.manual_page_variables[instrument_index][1].get())))
        newbuttons[7].bind('<Return>', lambda event: self.manual_queue.put((self.instruments[instrument_index].set_refill_rate, self.manual_page_variables[instrument_index][2].get())))
        newbuttons[16].bind('<Return>', lambda event: self.manual_queue.put((self.instruments[instrument_index].set_target_vol, self.manual_page_variables[instrument_index][3].get())))
        self.manual_page_buttons.append(newbuttons)
        # Build Pump
        for i in range(len(self.manual_page_buttons)):
            for y in range(len(self.manual_page_buttons[i])):
                self.manual_page_buttons[i][y].grid(row=i+1, column=y, sticky=tk.W+tk.E)

    def refresh_com_list(self):
        self.AvailablePorts = SAXSDrivers.list_available_ports()
        self.ControllerCOM.updatelist(self.AvailablePorts)
        for button in self.setup_page_buttons:
            if isinstance(button[0], COMPortSelector.COMPortSelector):
                button[0].updatelist(self.AvailablePorts)

    def add_rheodyne_set_buttons(self, address=-1, name="Rheodyne", hardware="", pc_connect=True):
        self.instruments.append(SAXSDrivers.Rheodyne(logger=self.python_logger, address_I2C=address, name=name, hardware_configuration=hardware, lock=self._lock, pc_connect=pc_connect))
        instrument_index = len(self.instruments)-1
        newvars = [tk.IntVar(value=address), tk.StringVar(value=name), tk.IntVar(value=2), tk.StringVar(value=hardware)]
        self.setup_page_variables.append(newvars)
        self.python_logger.info("Added Rheodyne")
        newbuttons = [
         COMPortSelector.COMPortSelector(self.setup_page, exportselection=0, height=4),
         tk.Button(self.setup_page, text="Set Port", command=lambda: self.instruments[instrument_index].set_port(self.AvailablePorts[int(self.setup_page_buttons[instrument_index][0].curselection()[0])].device)),
         tk.Button(self.setup_page, text="Send to Controller", command=lambda: self.instruments[instrument_index].set_to_controller(self.controller)),
         tk.Label(self.setup_page, text="   Type:", bg=self.label_bg_color),
         tk.Spinbox(self.setup_page, values=(2, 6), textvariable=self.setup_page_variables[instrument_index][2], width=6),
         tk.Label(self.setup_page, text="   I2C Address:", bg=self.label_bg_color),
         tk.Spinbox(self.setup_page, from_=-1, to=100, textvariable=self.setup_page_variables[instrument_index][0], width=6),
         tk.Label(self.setup_page, text="   Valve Name:", bg=self.label_bg_color),
         tk.Entry(self.setup_page, textvariable=self.setup_page_variables[instrument_index][1], width=10),
         tk.Button(self.setup_page, text="Set values", command=lambda: self.instrument_change_values(instrument_index, True))
         ]
        self.setup_page_buttons.append(newbuttons)
        for i in range(len(self.setup_page_buttons)):
            for y in range(len(self.setup_page_buttons[i])):
                self.setup_page_buttons[i][y].grid(row=i+2, column=y, sticky=tk.W+tk.E)
        self.AddRheodyneControlButtons()
        #self.refresh_com_list()
        if hardware != "":
            self.configure_to_hardware(hardware, instrument_index)
        # self.refresh_dropdown()

    def AddRheodyneControlButtons(self):
        instrument_index = len(self.instruments)-1
        newvars = [tk.StringVar(), tk.IntVar(value=0)]
        newvars[0].set(self.instruments[instrument_index].name+":  ")
        self.manual_page_variables.append(newvars)

        newbuttons = [
         tk.Label(self.manual_page, textvariable=self.manual_page_variables[instrument_index][0], bg=self.label_bg_color, font=self.manual_button_font),
         tk.Label(self.manual_page, text="   Position:", bg=self.label_bg_color, font=self.manual_button_font),
         tk.Spinbox(self.manual_page, from_=1, to=self.setup_page_variables[instrument_index][2].get(), textvariable=self.manual_page_variables[instrument_index][1], width=4, font=self.manual_button_font),
         tk.Button(self.manual_page, text="Change", command=lambda: self.manual_queue.put((self.instruments[instrument_index].switchvalve, self.manual_page_variables[instrument_index][1].get())), font=self.manual_button_font),
         ]
        newbuttons[2].bind('<Return>', lambda event: self.manual_queue.put((self.instruments[instrument_index].switchvalve, self.manual_page_variables[instrument_index][1].get())))
        self.manual_page_buttons.append(newbuttons)
        # Place buttons
        for i in range(len(self.manual_page_buttons)):
            for y in range(len(self.manual_page_buttons[i])):
                self.manual_page_buttons[i][y].grid(row=i+1, column=y, sticky=tk.W)

    def AddVICISetButtons(self, name="VICI", hardware="", pc_connect=True, address="", silent=False):
        self.instruments.append(SAXSDrivers.VICI(logger=self.python_logger, name=name, hardware_configuration=hardware, lock=self._lock, pc_connect=pc_connect, address=address, silent=silent))
        instrument_index = len(self.instruments)-1
        newvars = [tk.IntVar(value=-1), tk.StringVar(value=name), tk.StringVar(value=hardware)]
        self.setup_page_variables.append(newvars)
        self.python_logger.info("Added VICI Valve")
        newbuttons = [
         COMPortSelector.COMPortSelector(self.setup_page, exportselection=0, height=4),
         tk.Button(self.setup_page, text="Set Port", command=lambda: self.instruments[instrument_index].set_port(self.AvailablePorts[int(self.setup_page_buttons[instrument_index][0].curselection()[0])].device)),
         tk.Button(self.setup_page, text="Send to Controller", command=lambda:self.instruments[instrument_index].set_to_controller(self.controller)),
         tk.Label(self.setup_page, text="   Valve Name:", bg=self.label_bg_color),
         tk.Entry(self.setup_page, textvariable=self.setup_page_variables[instrument_index][1], width=10),
         tk.Button(self.setup_page, text="Set values", command=lambda: self.instrument_change_values(instrument_index, False))
         ]
        self.setup_page_buttons.append(newbuttons)
        for i in range(len(self.setup_page_buttons)):
            for y in range(len(self.setup_page_buttons[i])):
                self.setup_page_buttons[i][y].grid(row=i+2, column=y, sticky=tk.W+tk.E)
        self.AddVICIControlButtons()
        #self.refresh_com_list()
        if hardware != "":
            self.configure_to_hardware(hardware, instrument_index)

    def AddVICIControlButtons(self):
        instrument_index = len(self.instruments)-1
        newvars = [tk.StringVar(), tk.StringVar(value="A")]
        newvars[0].set(self.instruments[instrument_index].name+":  ")
        self.manual_page_variables.append(newvars)

        newbuttons = [
         tk.Label(self.manual_page, textvariable=self.manual_page_variables[instrument_index][0], bg=self.label_bg_color, font=self.manual_button_font),
         tk.Label(self.manual_page, text="   Position:", bg=self.label_bg_color, font=self.manual_button_font),
         tk.Spinbox(self.manual_page, values=("A", "B"), textvariable=self.manual_page_variables[instrument_index][1], width=4, font=self.manual_button_font),
         tk.Button(self.manual_page, text="Change", command=lambda: self.manual_queue.put((self.instruments[instrument_index].switchvalve, self.manual_page_variables[instrument_index][1].get())), font=self.manual_button_font)
         ]
        newbuttons[2].bind('<Return>', lambda event: self.manual_queue.put((self.instruments[instrument_index].switchvalve, self.manual_page_variables[instrument_index][1].get())))
        self.manual_page_buttons.append(newbuttons)
        # Place buttons
        for i in range(len(self.manual_page_buttons)):
            for y in range(len(self.manual_page_buttons[i])):
                self.manual_page_buttons[i][y].grid(row=i+1, column=y)

    def volume_count_down(self):

        if self.pumps_running_bool:
            self.lower_vol()
            self.main_window.after(1000, self.volume_count_down)
        else:
            pass

    def lower_vol(self):
        if self.running_pos == "buffer":
            self.remaining_buffer_vol_var.set(round(self.remaining_buffer_vol_var.get()-self.auto_flowrate_variable.get()/60000.0,5))
            if self.remaining_buffer_vol_var.get()<=0:
                self.run_pumps_button_command()
        elif self.running_pos == "sample":
            self.remaining_sample_vol_var.set(round(self.remaining_sample_vol_var.get()-self.auto_flowrate_variable.get()/60000.0,5))
            if self.remaining_sample_vol_var.get()<=0:
                self.run_pumps_button_command()

if __name__ == "__main__":
    window = tk.Tk()
    print("initializing GUI...")
    Main(window)
    window.mainloop()
    print("Main window now destroyed. Exiting.")
