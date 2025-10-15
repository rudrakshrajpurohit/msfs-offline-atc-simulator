"""
MSFS Offline ATC Simulation System - MSFS-Style GUI Control Panel
Complete interactive ATC interface with clickable commands and real-time updates
Enhanced with Frequency Management, Airspace Awareness, and Controller Personalities
"""

import time
import math
import random
import requests
import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Tuple, Callable, List
import subprocess
import os
import tempfile
from queue import Queue
import winsound

try:
    import pyttsx3
except ImportError:
    pyttsx3 = None

try:
    from SimConnect import SimConnect, AircraftRequests
except ImportError:
    SimConnect = None

# ============================================================================
# CONFIGURATION
# ============================================================================

SIMBRIEF_USERNAME = "walker79044"  # Your SimBrief username
POLL_INTERVAL = 2.0  # Seconds between updates
SPEECH_RATE = 1.0  # TTS speed multiplier

# Piper TTS Configuration (primary)
PIPER_MODEL_PATH = r"C:\piper"
PIPER_EXECUTABLE = r"C:\piper\piper.exe"
PIPER_MODEL_FILE = "en_US-lessac-medium.onnx"

# pyttsx3 Configuration (fallback)
PYTTSX3_RATE = 160
PYTTSX3_VOLUME = 0.9

# Flight phase thresholds
TAXI_ALTITUDE_THRESHOLD = 50
TAKEOFF_ALTITUDE = 100
INITIAL_CLIMB_ALTITUDE = 1500
APPROACH_ALTITUDE = 10000
FINAL_APPROACH_ALTITUDE = 3000
LANDING_SPEED = 60

# GUI Colors (MSFS-inspired)
COLOR_BG = "#1a1a1a"
COLOR_PANEL = "#2a2a2a"
COLOR_TEXT = "#e0e0e0"
COLOR_ACCENT = "#4a90e2"
COLOR_SUCCESS = "#4caf50"
COLOR_WARNING = "#ff9800"
COLOR_ERROR = "#f44336"

# ============================================================================
# NATO PHONETIC ALPHABET
# ============================================================================

NATO_PHONETIC = {
    'A': 'Alpha', 'B': 'Bravo', 'C': 'Charlie', 'D': 'Delta', 'E': 'Echo',
    'F': 'Foxtrot', 'G': 'Golf', 'H': 'Hotel', 'I': 'India', 'J': 'Juliet',
    'K': 'Kilo', 'L': 'Lima', 'M': 'Mike', 'N': 'November', 'O': 'Oscar',
    'P': 'Papa', 'Q': 'Quebec', 'R': 'Romeo', 'S': 'Sierra', 'T': 'Tango',
    'U': 'Uniform', 'V': 'Victor', 'W': 'Whiskey', 'X': 'X-ray', 'Y': 'Yankee',
    'Z': 'Zulu', '0': 'Zero', '1': 'One', '2': 'Two', '3': 'Three', '4': 'Four',
    '5': 'Five', '6': 'Six', '7': 'Seven', '8': 'Eight', '9': 'Niner'
}

def convert_to_nato(text: str) -> str:
    """Convert text to NATO phonetic alphabet"""
    result = []
    for char in text.upper():
        if char in NATO_PHONETIC:
            result.append(NATO_PHONETIC[char])
        elif char.isspace():
            continue
        else:
            result.append(char)
    return ' '.join(result)

def format_callsign_nato(callsign: str) -> str:
    """Format callsign with NATO phonetic"""
    prefixes = ["SPEEDBIRD", "LUFTHANSA", "UNITED", "DELTA", "AMERICAN"]
    for prefix in prefixes:
        if callsign.startswith(prefix):
            return prefix.capitalize() + " " + convert_to_nato(callsign[len(prefix):])
    return convert_to_nato(callsign)

def generate_squawk_code() -> str:
    """Generate random squawk code (octal, avoiding reserved codes)"""
    # Avoid 0000, 7500, 7600, 7700
    reserved = {'0000', '7500', '7600', '7700'}
    while True:
        code = ''.join([str(random.randint(0, 7)) for _ in range(4)])
        if code not in reserved:
            return code

def generate_frequency(freq_type: str) -> str:
    """Generate realistic radio frequency"""
    freq_ranges = {
        'clearance': (121, 700, 900),
        'ground': (121, 600, 900),
        'tower': (118, 100, 900),
        'departure': (119, 100, 900),
        'approach': (120, 100, 900),
        'center': (132, 100, 900)
    }
    base, min_dec, max_dec = freq_ranges.get(freq_type, (121, 500, 900))
    decimal = random.randint(min_dec, max_dec)
    # Ensure 25 kHz spacing (ends in 00, 25, 50, 75)
    decimal = (decimal // 25) * 25
    return f"{base}.{decimal:03d}"

# ============================================================================
# ENUMS AND DATA CLASSES
# ============================================================================

class ATCPhase(Enum):
    COLD_AND_DARK = "Cold & Dark"
    CLEARANCE_DELIVERY = "Clearance Delivery"
    PUSHBACK_APPROVED = "Pushback Approved"
    TAXI_OUT = "Taxi Out"
    LINEUP_CLEARANCE = "Line Up"
    TAKEOFF_CLEARANCE = "Takeoff Clearance"
    DEPARTURE = "Departure"
    CLIMB = "Climb"
    CRUISE = "Cruise"
    TOD_ADVISORY = "Top of Descent"
    DESCENT = "Descent"
    APPROACH = "Approach"
    FINAL_APPROACH = "Final Approach"
    LANDING_CLEARANCE = "Landing Clearance"
    LANDED = "Landed"
    TAXI_IN = "Taxi In"
    PARKING = "Parking"
    COMPLETE = "Complete"

class ATCPosition(Enum):
    CLEARANCE_DELIVERY = "Clearance"
    GROUND = "Ground"
    TOWER = "Tower"
    DEPARTURE = "Departure"
    CENTER = "Center"
    APPROACH = "Approach"

@dataclass
class FlightPlan:
    callsign: str
    departure_icao: str
    departure_runway: str
    arrival_icao: str
    arrival_runway: str
    sid: str
    star: str
    cruise_altitude: int
    cruise_altitude_fl: str
    route: str
    distance_nm: float
    squawk: str = "2000"
    
    def get_tod_distance(self) -> float:
        altitude_to_lose = self.cruise_altitude - 3000
        return (altitude_to_lose / 1000) * 3 + 10

@dataclass
class AircraftState:
    latitude: float
    longitude: float
    altitude_msl: float
    altitude_agl: float
    groundspeed: int
    heading: int
    on_ground: bool
    vertical_speed: float
    
    def distance_to(self, lat2: float, lon2: float) -> float:
        R = 3440.065
        lat1, lon1 = math.radians(self.latitude), math.radians(self.longitude)
        lat2, lon2 = math.radians(lat2), math.radians(lon2)
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
        return R * 2 * math.asin(math.sqrt(a))

AIRPORT_DATABASE = {
    "EGLL": {"name": "London Heathrow", "lat": 51.4700, "lon": -0.4543},
    "EDDF": {"name": "Frankfurt", "lat": 50.0379, "lon": 8.5622},
    "KJFK": {"name": "Kennedy", "lat": 40.6413, "lon": -73.7781},
    "KLAX": {"name": "Los Angeles", "lat": 33.9416, "lon": -118.4085},
    "LFPG": {"name": "Paris CDG", "lat": 49.0097, "lon": 2.5479},
}

# ============================================================================
# TTS MANAGER
# ============================================================================

class TTSManager:
    """Manages TTS engines with Piper primary and pyttsx3 fallback"""
    
    def __init__(self):
        self.engine = None
        self.speaking = False
        self.tts_queue = Queue()
        self._init_engine()
        self._start_worker()
    
    def _init_engine(self):
        """Initialize TTS engine"""
        try:
            self.engine = PiperTTS()
            print("TTS: Piper initialized")
        except Exception as e:
            print(f"TTS: Piper failed ({e}), using pyttsx3")
            try:
                self.engine = PyTTSX3Fallback()
            except Exception as e2:
                print(f"TTS: All engines failed ({e2})")
                self.engine = None
    
    def _start_worker(self):
        """Start background worker thread"""
        def worker():
            while True:
                text = self.tts_queue.get()
                if text is None:
                    break
                if self.engine:
                    self.engine.speak(text)
                self.tts_queue.task_done()
        
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
    
    def speak(self, text: str):
        """Queue text for speech"""
        self.tts_queue.put(text)

class PiperTTS:
    """Piper TTS engine"""
    
    def __init__(self):
        self.executable = PIPER_EXECUTABLE
        self.model = os.path.join(PIPER_MODEL_PATH, "models", PIPER_MODEL_FILE)
        self.temp_dir = tempfile.gettempdir()
        
        if not os.path.exists(self.executable):
            raise FileNotFoundError(f"Piper executable not found: {self.executable}")
        if not os.path.exists(self.model):
            raise FileNotFoundError(f"Piper model not found: {self.model}")
    
    def speak(self, text: str):
        """Generate and play speech"""
        try:
            output_path = os.path.join(self.temp_dir, f"atc_{time.time()}.wav")
            
            process = subprocess.Popen(
                [self.executable, "-m", self.model, "-f", output_path],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, 
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            process.communicate(input=text.encode(), timeout=30)
            
            if process.returncode == 0 and os.path.exists(output_path):
                # Use winsound for non-blocking playback on Windows
                if os.name == 'nt':
                    winsound.PlaySound(output_path, winsound.SND_FILENAME | winsound.SND_ASYNC)
                    # Wait for playback to finish (approximate)
                    time.sleep(len(text) * 0.05)  # Rough estimate
                else:
                    os.system(f'afplay "{output_path}" 2>/dev/null || aplay "{output_path}" 2>/dev/null')
                
                # Clean up after a delay
                try:
                    time.sleep(1)
                    if os.path.exists(output_path):
                        os.remove(output_path)
                except:
                    pass
        except Exception as e:
            print(f"Piper error: {e}")

class PyTTSX3Fallback:
    """pyttsx3 fallback engine"""
    
    def __init__(self):
        if pyttsx3 is None:
            raise ImportError("pyttsx3 not available")
        self.engine = pyttsx3.init()
        self.engine.setProperty('rate', PYTTSX3_RATE)
        self.engine.setProperty('volume', PYTTSX3_VOLUME)
    
    def speak(self, text: str):
        """Speak using pyttsx3"""
        try:
            self.engine.say(text)
            self.engine.runAndWait()
        except Exception as e:
            print(f"pyttsx3 error: {e}")

# ============================================================================
# CONTROLLER PERSONALITY SYSTEM
# ============================================================================

class ControllerPersonality:
    """Define personality traits for different ATC positions"""
    
    def __init__(self, position_name: str, traits: dict):
        self.position_name = position_name
        self.formality = traits.get('formality', 0.7)  # 0-1 scale
        self.friendliness = traits.get('friendliness', 0.5)
        self.verbosity = traits.get('verbosity', 0.5)
        self.strictness = traits.get('strictness', 0.5)
        self.speech_rate = traits.get('speech_rate', 1.0)
    
    def modify_phrase(self, base_phrase: str, context: str = 'normal') -> str:
        """Apply personality variations to phrases"""
        phrase = base_phrase
        
        # Friendly variations
        if self.friendliness > 0.7 and 'good day' in phrase.lower():
            if random.random() < 0.3:
                phrase = phrase.replace('good day', random.choice([
                    'safe flight', 'have a good one', 'fly safe'
                ]))
        
        # Strict/concise variations (remove courtesy words)
        if self.strictness > 0.7 and self.verbosity < 0.4:
            phrase = phrase.replace(', advise ready to taxi', '')
            phrase = phrase.replace(' please', '')
        
        # Verbose variations (add extra info)
        if self.verbosity > 0.7:
            if 'maintain' in phrase.lower() and random.random() < 0.4:
                phrase = phrase.replace('.', ', thank you.')
        
        return phrase
    
    def get_description(self) -> str:
        """Get personality description for display"""
        traits = []
        if self.formality > 0.7:
            traits.append("Formal")
        if self.friendliness > 0.6:
            traits.append("Friendly")
        if self.strictness > 0.7:
            traits.append("Strict")
        if self.verbosity < 0.4:
            traits.append("Concise")
        elif self.verbosity > 0.7:
            traits.append("Verbose")
        return f"Personality: {', '.join(traits) if traits else 'Standard'}"

# Pre-defined controller personalities
CONTROLLER_PERSONALITIES = {
    ATCPosition.CLEARANCE_DELIVERY: ControllerPersonality('Clearance Delivery', {
        'formality': 0.9, 'friendliness': 0.5, 'verbosity': 0.8, 'strictness': 0.7
    }),
    ATCPosition.GROUND: ControllerPersonality('Ground Control', {
        'formality': 0.8, 'friendliness': 0.4, 'verbosity': 0.3, 'strictness': 0.9
    }),
    ATCPosition.TOWER: ControllerPersonality('Tower', {
        'formality': 0.8, 'friendliness': 0.6, 'verbosity': 0.5, 'strictness': 0.8
    }),
    ATCPosition.DEPARTURE: ControllerPersonality('Departure', {
        'formality': 0.7, 'friendliness': 0.6, 'verbosity': 0.6, 'strictness': 0.6
    }),
    ATCPosition.CENTER: ControllerPersonality('Center', {
        'formality': 0.6, 'friendliness': 0.7, 'verbosity': 0.7, 'strictness': 0.5
    }),
    ATCPosition.APPROACH: ControllerPersonality('Approach', {
        'formality': 0.7, 'friendliness': 0.7, 'verbosity': 0.6, 'strictness': 0.7
    })
}

# ============================================================================
# AIRSPACE CLASSIFICATION SYSTEM
# ============================================================================

class AirspaceClass(Enum):
    CLASS_A = "Class A"  # FL180 and above
    CLASS_B = "Class B"  # Major airport terminal areas
    CLASS_C = "Class C"  # Medium airport terminal areas
    CLASS_D = "Class D"  # Small controlled airports
    CLASS_E = "Class E"  # Controlled airspace
    CLASS_G = "Class G"  # Uncontrolled airspace

@dataclass
class AirspaceVolume:
    """Define an airspace volume"""
    name: str
    classification: AirspaceClass
    center_lat: float
    center_lon: float
    radius_nm: float  # Nautical miles
    floor_ft: float   # Feet MSL
    ceiling_ft: float # Feet MSL

class AirspaceMonitor:
    """Monitor aircraft airspace transitions"""
    
    def __init__(self):
        self.current_airspace = AirspaceClass.CLASS_G
        self.airspace_volumes: List[AirspaceVolume] = []
        self.last_announcement = None
        self._init_default_airspaces()
    
    def _init_default_airspaces(self):
        """Initialize default airspace structures"""
        # Class A (high altitude enroute)
        self.airspace_volumes.append(AirspaceVolume(
            "High Altitude Airspace", AirspaceClass.CLASS_A,
            0, 0, 999999, 18000, 60000  # Covers all, FL180+
        ))
        
        # Class B (major terminal areas - examples)
        for icao, data in AIRPORT_DATABASE.items():
            self.airspace_volumes.append(AirspaceVolume(
                f"{data['name']} Class B", AirspaceClass.CLASS_B,
                data['lat'], data['lon'], 30, 0, 10000
            ))
        
        # Class E (general controlled airspace)
        self.airspace_volumes.append(AirspaceVolume(
            "Controlled Airspace", AirspaceClass.CLASS_E,
            0, 0, 999999, 1200, 17999
        ))
        
        # Class G is default (uncontrolled)
    
    def check_airspace(self, aircraft_state: AircraftState) -> Tuple[AirspaceClass, bool]:
        """Check current airspace and detect transitions"""
        new_airspace = self._determine_airspace(aircraft_state)
        changed = new_airspace != self.current_airspace
        
        if changed:
            self.current_airspace = new_airspace
        
        return new_airspace, changed
    
    def _determine_airspace(self, aircraft_state: AircraftState) -> AirspaceClass:
        """Determine airspace based on position and altitude"""
        # Check Class A first (altitude-based)
        if aircraft_state.altitude_msl >= 18000:
            return AirspaceClass.CLASS_A
        
        # Check defined volumes
        for volume in self.airspace_volumes:
            if self._is_in_volume(aircraft_state, volume):
                return volume.classification
        
        # Default to Class G
        return AirspaceClass.CLASS_G
    
    def _is_in_volume(self, aircraft_state: AircraftState, volume: AirspaceVolume) -> bool:
        """Check if aircraft is within airspace volume"""
        # Altitude check
        if not (volume.floor_ft <= aircraft_state.altitude_msl <= volume.ceiling_ft):
            return False
        
        # Distance check (simplified)
        distance = aircraft_state.distance_to(volume.center_lat, volume.center_lon)
        return distance <= volume.radius_nm
    
    def get_entry_message(self, airspace: AirspaceClass, callsign: str) -> str:
        """Generate airspace entry announcement"""
        messages = {
            AirspaceClass.CLASS_A: f"{callsign}, entering Class Alpha airspace, flight level one eight zero and above.",
            AirspaceClass.CLASS_B: f"{callsign}, entering Class Bravo airspace, maintain assigned altitude.",
            AirspaceClass.CLASS_C: f"{callsign}, Class Charlie airspace, radar contact.",
            AirspaceClass.CLASS_D: f"{callsign}, entering Class Delta airspace.",
            AirspaceClass.CLASS_E: f"{callsign}, controlled airspace.",
            AirspaceClass.CLASS_G: f"{callsign}, uncontrolled airspace, VFR advisories available."
        }
        return messages.get(airspace, "")

# ============================================================================
# FREQUENCY & SECTOR MANAGEMENT
# ============================================================================

@dataclass
class ATCSector:
    """Define an ATC sector with geographic and altitude boundaries"""
    name: str
    position: ATCPosition
    frequency: str
    center_lat: float
    center_lon: float
    radius_nm: float
    alt_min: float  # Feet MSL
    alt_max: float  # Feet MSL
    personality: ControllerPersonality
    
    def is_in_sector(self, aircraft_state: AircraftState) -> bool:
        """Check if aircraft is within this sector"""
        # Altitude check
        if not (self.alt_min <= aircraft_state.altitude_msl <= self.alt_max):
            return False
        
        # Distance check
        distance = aircraft_state.distance_to(self.center_lat, self.center_lon)
        return distance <= self.radius_nm
    
    def distance_to_boundary(self, aircraft_state: AircraftState) -> float:
        """Calculate distance to sector boundary"""
        distance_to_center = aircraft_state.distance_to(self.center_lat, self.center_lon)
        return self.radius_nm - distance_to_center

class FrequencyManager:
    """Manage ATC frequencies and sector transitions"""
    
    def __init__(self, flight_plan: FlightPlan):
        self.active_frequency: Optional[str] = None
        self.active_sector: Optional[ATCSector] = None
        self.sectors: List[ATCSector] = []
        self.handoff_threshold_nm = 15  # Distance to trigger handoff
        self.pending_handoff: Optional[ATCSector] = None
        self._init_sectors(flight_plan)
    
    def _init_sectors(self, flight_plan: FlightPlan):
        """Initialize ATC sectors based on flight plan"""
        dep_data = AIRPORT_DATABASE.get(flight_plan.departure_icao, {'lat': 0, 'lon': 0, 'name': 'Unknown'})
        arr_data = AIRPORT_DATABASE.get(flight_plan.arrival_icao, {'lat': 0, 'lon': 0, 'name': 'Unknown'})
        
        # Departure sectors
        self.sectors.append(ATCSector(
            f"{flight_plan.departure_icao} Clearance",
            ATCPosition.CLEARANCE_DELIVERY,
            generate_frequency('clearance'),
            dep_data['lat'], dep_data['lon'], 5, 0, 1000,
            CONTROLLER_PERSONALITIES[ATCPosition.CLEARANCE_DELIVERY]
        ))
        
        self.sectors.append(ATCSector(
            f"{flight_plan.departure_icao} Ground",
            ATCPosition.GROUND,
            generate_frequency('ground'),
            dep_data['lat'], dep_data['lon'], 5, 0, 500,
            CONTROLLER_PERSONALITIES[ATCPosition.GROUND]
        ))
        
        self.sectors.append(ATCSector(
            f"{flight_plan.departure_icao} Tower",
            ATCPosition.TOWER,
            generate_frequency('tower'),
            dep_data['lat'], dep_data['lon'], 10, 0, 3000,
            CONTROLLER_PERSONALITIES[ATCPosition.TOWER]
        ))
        
        self.sectors.append(ATCSector(
            f"{flight_plan.departure_icao} Departure",
            ATCPosition.DEPARTURE,
            generate_frequency('departure'),
            dep_data['lat'], dep_data['lon'], 40, 500, 18000,
            CONTROLLER_PERSONALITIES[ATCPosition.DEPARTURE]
        ))
        
        # Enroute sector (Center)
        mid_lat = (dep_data['lat'] + arr_data['lat']) / 2
        mid_lon = (dep_data['lon'] + arr_data['lon']) / 2
        
        self.sectors.append(ATCSector(
            "Center",
            ATCPosition.CENTER,
            generate_frequency('center'),
            mid_lat, mid_lon, 200, 18000, 60000,
            CONTROLLER_PERSONALITIES[ATCPosition.CENTER]
        ))
        
        # Arrival sectors
        self.sectors.append(ATCSector(
            f"{flight_plan.arrival_icao} Approach",
            ATCPosition.APPROACH,
            generate_frequency('approach'),
            arr_data['lat'], arr_data['lon'], 40, 1000, 18000,
            CONTROLLER_PERSONALITIES[ATCPosition.APPROACH]
        ))
        
        self.sectors.append(ATCSector(
            f"{flight_plan.arrival_icao} Tower",
            ATCPosition.TOWER,
            generate_frequency('tower'),
            arr_data['lat'], arr_data['lon'], 10, 0, 3000,
            CONTROLLER_PERSONALITIES[ATCPosition.TOWER]
        ))
        
        self.sectors.append(ATCSector(
            f"{flight_plan.arrival_icao} Ground",
            ATCPosition.GROUND,
            generate_frequency('ground'),
            arr_data['lat'], arr_data['lon'], 5, 0, 500,
            CONTROLLER_PERSONALITIES[ATCPosition.GROUND]
        ))
    
    def set_active_frequency(self, frequency: str) -> bool:
        """Set active frequency and find corresponding sector"""
        for sector in self.sectors:
            if sector.frequency == frequency:
                self.active_frequency = frequency
                self.active_sector = sector
                return True
        return False
    
    def find_appropriate_sector(self, aircraft_state: AircraftState) -> Optional[ATCSector]:
        """Find the sector aircraft should be in"""
        for sector in self.sectors:
            if sector.is_in_sector(aircraft_state):
                return sector
        return None
    
    def check_handoff_needed(self, aircraft_state: AircraftState) -> Optional[ATCSector]:
        """Check if handoff to next sector is needed"""
        if not self.active_sector:
            return None
        
        # Check if approaching boundary
        distance_to_boundary = self.active_sector.distance_to_boundary(aircraft_state)
        
        if distance_to_boundary < self.handoff_threshold_nm:
            # Find next appropriate sector
            next_sector = self.find_appropriate_sector(aircraft_state)
            if next_sector and next_sector != self.active_sector:
                return next_sector
        
        return None
    
    def get_frequency_list(self) -> List[Tuple[str, str, str]]:
        """Get list of all frequencies for display"""
        freq_list = []
        seen = set()
        for sector in self.sectors:
            key = (sector.position.value, sector.frequency)
            if key not in seen:
                freq_list.append((sector.position.value, sector.frequency, sector.name))
                seen.add(key)
        return freq_list

# ============================================================================
# ENHANCED ATC PHRASEOLOGY (WITH PERSONALITY)
# ============================================================================

class ATCPhraseology:
    """Generate realistic ATC messages with NATO phonetic and personality"""
    
    @staticmethod
    def apply_personality(message: str, personality: ControllerPersonality, context: str = 'normal') -> str:
        """Apply controller personality to message"""
        return personality.modify_phrase(message, context)
    
    @staticmethod
    def clearance_delivery(fp: FlightPlan, departure_freq: str, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        callsign = format_callsign_nato(fp.callsign)
        squawk = convert_to_nato(fp.squawk)
        message = (f"{callsign}, Clearance Delivery, cleared to {fp.arrival_icao} "
                  f"via {fp.sid} departure, flight planned route, "
                  f"climb and maintain flight level {fp.cruise_altitude_fl}, "
                  f"departure frequency {departure_freq}, squawk {squawk}.")
        if personality:
            message = personality.modify_phrase(message, 'clearance')
        return (message, ATCPosition.CLEARANCE_DELIVERY)
    
    @staticmethod
    def pushback_clearance(callsign: str, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        """Generate pushback clearance"""
        message = f"{format_callsign_nato(callsign)}, pushback approved, tail north, advise ready to taxi."
        if personality:
            message = personality.modify_phrase(message, 'pushback')
        return (message, ATCPosition.GROUND)
    
    @staticmethod
    def frequency_handoff(callsign: str, next_controller: str, next_freq: str, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        """Generate frequency handoff message"""
        callsign_nato = format_callsign_nato(callsign)
        message = f"{callsign_nato}, contact {next_controller} {next_freq}. Good day."
        if personality:
            message = personality.modify_phrase(message, 'handoff')
        return (message, ATCPosition.CENTER)  # Position will be overridden
    
    @staticmethod
    def check_in_response(callsign: str, altitude_fl: str, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        """Generate check-in acknowledgment"""
        callsign_nato = format_callsign_nato(callsign)
        message = f"{callsign_nato}, radar contact. Maintain flight level {altitude_fl}."
        if personality:
            message = personality.modify_phrase(message, 'checkin')
        return (message, ATCPosition.CENTER)
    
    @staticmethod
    def taxi_out(callsign: str, runway: str, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        message = f"{format_callsign_nato(callsign)}, taxi to runway {convert_to_nato(runway)} via taxiway Alpha, hold short."
        if personality:
            message = personality.modify_phrase(message, 'taxi')
        return (message, ATCPosition.GROUND)
    
    @staticmethod
    def lineup_clearance(callsign: str, runway: str, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        message = f"{format_callsign_nato(callsign)}, runway {convert_to_nato(runway)}, line up and wait."
        if personality:
            message = personality.modify_phrase(message, 'lineup')
        return (message, ATCPosition.TOWER)
    
    @staticmethod
    def takeoff_clearance(callsign: str, runway: str, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        message = f"{format_callsign_nato(callsign)}, runway {convert_to_nato(runway)}, wind calm, cleared for takeoff."
        if personality:
            message = personality.modify_phrase(message, 'takeoff')
        return (message, ATCPosition.TOWER)
    
    @staticmethod
    def contact_departure(callsign: str, freq: str, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        message = f"{format_callsign_nato(callsign)}, contact departure {freq}."
        if personality:
            message = personality.modify_phrase(message, 'handoff')
        return (message, ATCPosition.TOWER)
    
    @staticmethod
    def climb_clearance(callsign: str, altitude_fl: str, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        message = f"{format_callsign_nato(callsign)}, climb flight level {altitude_fl}."
        if personality:
            message = personality.modify_phrase(message, 'climb')
        return (message, ATCPosition.DEPARTURE)
    
    @staticmethod
    def cruise_check(callsign: str, altitude_fl: str, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        message = f"{format_callsign_nato(callsign)}, maintaining flight level {altitude_fl}."
        if personality:
            message = personality.modify_phrase(message, 'cruise')
        return (message, ATCPosition.CENTER)
    
    @staticmethod
    def top_of_descent(callsign: str, distance: int, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        message = f"{format_callsign_nato(callsign)}, top of descent in {distance} miles."
        if personality:
            message = personality.modify_phrase(message, 'tod')
        return (message, ATCPosition.CENTER)
    
    @staticmethod
    def descent_clearance(callsign: str, altitude: int, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        message = f"{format_callsign_nato(callsign)}, descend and maintain {altitude} feet."
        if personality:
            message = personality.modify_phrase(message, 'descent')
        return (message, ATCPosition.CENTER)
    
    @staticmethod
    def expect_star(callsign: str, star: str, runway: str, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        message = f"{format_callsign_nato(callsign)}, expect {star} arrival, runway {convert_to_nato(runway)}."
        if personality:
            message = personality.modify_phrase(message, 'star')
        return (message, ATCPosition.CENTER)
    
    @staticmethod
    def approach_clearance(callsign: str, runway: str, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        message = f"{format_callsign_nato(callsign)}, cleared ILS approach runway {convert_to_nato(runway)}."
        if personality:
            message = personality.modify_phrase(message, 'approach')
        return (message, ATCPosition.APPROACH)
    
    @staticmethod
    def contact_tower(callsign: str, freq: str, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        message = f"{format_callsign_nato(callsign)}, contact tower {freq}."
        if personality:
            message = personality.modify_phrase(message, 'handoff')
        return (message, ATCPosition.APPROACH)
    
    @staticmethod
    def landing_clearance(callsign: str, runway: str, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        message = f"{format_callsign_nato(callsign)}, runway {convert_to_nato(runway)}, wind calm, cleared to land."
        if personality:
            message = personality.modify_phrase(message, 'landing')
        return (message, ATCPosition.TOWER)
    
    @staticmethod
    def exit_runway(callsign: str, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        message = f"{format_callsign_nato(callsign)}, exit next taxiway, contact ground point niner."
        if personality:
            message = personality.modify_phrase(message, 'exit')
        return (message, ATCPosition.TOWER)
    
    @staticmethod
    def taxi_to_gate(callsign: str, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        message = f"{format_callsign_nato(callsign)}, taxi to gate via taxiway Bravo."
        if personality:
            message = personality.modify_phrase(message, 'taxi')
        return (message, ATCPosition.GROUND)
    
    @staticmethod
    def parking_complete(callsign: str, personality: ControllerPersonality = None) -> Tuple[str, ATCPosition]:
        message = f"{format_callsign_nato(callsign)}, parking complete, good day."
        if personality:
            message = personality.modify_phrase(message, 'parking')
        return (message, ATCPosition.GROUND)

# ============================================================================
# SIMBRIEF IMPORTER
# ============================================================================

class SimBriefImporter:
    """Import flight plans from SimBrief"""
    
    @staticmethod
    def fetch_flight_plan(username: str) -> Optional[FlightPlan]:
        """Fetch flight plan from SimBrief API"""
        try:
            url = f"https://www.simbrief.com/api/xml.fetcher.php?username={username}&json=1"
            response = requests.get(url, timeout=10)
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            origin = data.get('origin', {})
            destination = data.get('destination', {})
            general = data.get('general', {})
            
            navlog = data.get('navlog', {}).get('fix', [])
            
            return FlightPlan(
                callsign=data.get('atc', {}).get('callsign', 'UNKNOWN'),
                departure_icao=origin.get('icao_code', 'ZZZZ'),
                departure_runway=origin.get('plan_rwy', '27'),
                arrival_icao=destination.get('icao_code', 'ZZZZ'),
                arrival_runway=destination.get('plan_rwy', '25R'),
                sid=navlog[0].get('via_airway', 'DIRECT') if navlog else 'DIRECT',
                star=navlog[-2].get('via_airway', 'DIRECT') if len(navlog) > 1 else 'DIRECT',
                cruise_altitude=int(general.get('initial_altitude', 35000)),
                cruise_altitude_fl=f"{int(general.get('initial_altitude', 35000)) // 100:03d}",
                route=general.get('route', 'DCT'),
                distance_nm=float(general.get('air_distance', 0)),
                squawk=generate_squawk_code()
            )
        except Exception as e:
            print(f"SimBrief error: {e}")
            return None
    
    @staticmethod
    def create_demo_flight_plan() -> FlightPlan:
        """Create demo flight plan"""
        return FlightPlan(
            callsign="SPEEDBIRD123", departure_icao="EGLL", departure_runway="27R",
            arrival_icao="EDDF", arrival_runway="25C", sid="BUZAD2G", star="TEKTU1A",
            cruise_altitude=37000, cruise_altitude_fl="370",
            route="BUZAD L9 KONAN", distance_nm=420.0, squawk=generate_squawk_code()
        )

# ============================================================================
# SIMCONNECT INTERFACE
# ============================================================================

class SimConnectInterface:
    """Interface to MSFS via SimConnect"""
    
    def __init__(self):
        self.sm = None
        self.aq = None
        self.connected = False
    
    def connect(self) -> bool:
        """Connect to MSFS"""
        if SimConnect is None:
            return False
        try:
            self.sm = SimConnect()
            self.aq = AircraftRequests(self.sm, _time=0)
            self.connected = True
            return True
        except Exception as e:
            print(f"SimConnect error: {e}")
            return False
    
    def get_aircraft_state(self) -> Optional[AircraftState]:
        """Get current aircraft state"""
        if not self.connected:
            return None
        try:
            return AircraftState(
                latitude=float(self.aq.get("PLANE_LATITUDE") or 0.0),
                longitude=float(self.aq.get("PLANE_LONGITUDE") or 0.0),
                altitude_msl=float(self.aq.get("PLANE_ALTITUDE") or 0.0),
                altitude_agl=float(self.aq.get("PLANE_ALT_ABOVE_GROUND") or 0.0),
                groundspeed=int(self.aq.get("GROUND_VELOCITY") or 0),
                heading=int(self.aq.get("PLANE_HEADING_DEGREES_TRUE") or 0),
                on_ground=self.aq.get("SIM_ON_GROUND") == 1,
                vertical_speed=float(self.aq.get("VERTICAL_SPEED") or 0.0)
            )
        except Exception as e:
            print(f"Error reading state: {e}")
            return None
    
    def disconnect(self):
        """Disconnect from MSFS"""
        if self.sm:
            try:
                self.sm.exit()
            except:
                pass
            self.connected = False

# ============================================================================
# ATC CONTROLLER
# ============================================================================

class ATCController:
    """Main ATC logic controller"""
    
    def __init__(self, flight_plan: FlightPlan, tts_manager: TTSManager, callback: Callable):
        self.flight_plan = flight_plan
        self.tts = tts_manager
        self.callback = callback
        self.phase = ATCPhase.COLD_AND_DARK
        
        self.phase_announced = False
        self.cruise_check_done = False
        self.tod_announced = False
        self.descent_step = 0
        
        # Initialize frequency manager and airspace monitor
        self.frequency_manager = FrequencyManager(flight_plan)
        self.airspace_monitor = AirspaceMonitor()
        
        # Set initial frequency and personality
        if self.frequency_manager.sectors:
            initial_sector = self.frequency_manager.sectors[0]
            self.frequency_manager.set_active_frequency(initial_sector.frequency)
            self.current_personality = initial_sector.personality
        else:
            self.current_personality = CONTROLLER_PERSONALITIES[ATCPosition.CLEARANCE_DELIVERY]
        
        self.frequencies = {
            'clearance': generate_frequency('clearance'),
            'ground': generate_frequency('ground'),
            'tower': generate_frequency('tower'),
            'departure': generate_frequency('departure'),
            'approach': generate_frequency('approach'),
            'center': generate_frequency('center')
        }
        
        self.dest_lat = AIRPORT_DATABASE.get(flight_plan.arrival_icao, {}).get('lat', 0.0)
        self.dest_lon = AIRPORT_DATABASE.get(flight_plan.arrival_icao, {}).get('lon', 0.0)
    
    def speak(self, message: str, position: ATCPosition):
        """Issue ATC message"""
        self.callback(message, position, self.phase)
        self.tts.speak(message)
    
    def get_active_controller_info(self) -> Tuple[str, str, str]:
        """Get active controller information for GUI display"""
        if self.frequency_manager.active_sector:
            sector = self.frequency_manager.active_sector
            return (
                sector.name,
                sector.frequency,
                sector.personality.get_description()
            )
        else:
            return ("---", "---", "---")
    
    def request_clearance(self):
        """User requests IFR clearance"""
        if self.phase == ATCPhase.COLD_AND_DARK:
            personality = CONTROLLER_PERSONALITIES[ATCPosition.CLEARANCE_DELIVERY]
            msg, pos = ATCPhraseology.clearance_delivery(self.flight_plan,
                                                         self.frequencies['departure'],
                                                         personality)
            self.speak(msg, pos)
            self.phase = ATCPhase.CLEARANCE_DELIVERY
            self.phase_announced = True
    
    def request_pushback(self):
        """User requests pushback"""
        if self.phase in [ATCPhase.CLEARANCE_DELIVERY, ATCPhase.COLD_AND_DARK]:
            personality = CONTROLLER_PERSONALITIES[ATCPosition.GROUND]
            msg, pos = ATCPhraseology.pushback_clearance(self.flight_plan.callsign, personality)
            self.speak(msg, pos)
            self.phase = ATCPhase.PUSHBACK_APPROVED
            self.phase_announced = True
    
    def request_taxi(self):
        """User requests taxi"""
        if self.phase in [ATCPhase.PUSHBACK_APPROVED, ATCPhase.CLEARANCE_DELIVERY]:
            personality = CONTROLLER_PERSONALITIES[ATCPosition.GROUND]
            msg, pos = ATCPhraseology.taxi_out(self.flight_plan.callsign,
                                               self.flight_plan.departure_runway,
                                               personality)
            self.speak(msg, pos)
            self.phase = ATCPhase.TAXI_OUT
            self.phase_announced = True
    
    def request_takeoff(self):
        """User requests takeoff clearance"""
        if self.phase in [ATCPhase.TAXI_OUT, ATCPhase.LINEUP_CLEARANCE]:
            personality = CONTROLLER_PERSONALITIES[ATCPosition.TOWER]
            msg, pos = ATCPhraseology.lineup_clearance(self.flight_plan.callsign,
                                                       self.flight_plan.departure_runway,
                                                       personality)
            self.speak(msg, pos)
            time.sleep(3)
            msg, pos = ATCPhraseology.takeoff_clearance(self.flight_plan.callsign,
                                                        self.flight_plan.departure_runway,
                                                        personality)
            self.speak(msg, pos)
            self.phase = ATCPhase.TAKEOFF_CLEARANCE
            self.phase_announced = True
    
    def request_climb(self):
        """User requests climb clearance"""
        if self.phase in [ATCPhase.DEPARTURE, ATCPhase.CLIMB]:
            personality = CONTROLLER_PERSONALITIES[ATCPosition.DEPARTURE]
            msg, pos = ATCPhraseology.climb_clearance(self.flight_plan.callsign,
                                                      self.flight_plan.cruise_altitude_fl,
                                                      personality)
            self.speak(msg, pos)
            self.phase = ATCPhase.CLIMB
            self.phase_announced = True
    
    def request_cruise_altitude_change(self):
        """User requests cruise altitude change"""
        if self.phase == ATCPhase.CRUISE:
            new_alt = self.flight_plan.cruise_altitude + 2000
            personality = CONTROLLER_PERSONALITIES[ATCPosition.CENTER]
            msg, pos = ATCPhraseology.climb_clearance(self.flight_plan.callsign,
                                                      f"{new_alt // 100:03d}",
                                                      personality)
            self.speak(msg, pos)
    
    def request_descent(self):
        """User requests descent"""
        if self.phase in [ATCPhase.CRUISE, ATCPhase.TOD_ADVISORY]:
            personality = CONTROLLER_PERSONALITIES[ATCPosition.CENTER]
            msg, pos = ATCPhraseology.descent_clearance(self.flight_plan.callsign, 28000, personality)
            self.speak(msg, pos)
            self.phase = ATCPhase.DESCENT
            self.descent_step = 1
            self.phase_announced = True
    
    def request_landing(self):
        """User requests landing clearance"""
        if self.phase in [ATCPhase.APPROACH, ATCPhase.FINAL_APPROACH]:
            personality = CONTROLLER_PERSONALITIES[ATCPosition.TOWER]
            msg, pos = ATCPhraseology.landing_clearance(self.flight_plan.callsign,
                                                        self.flight_plan.arrival_runway,
                                                        personality)
            self.speak(msg, pos)
            self.phase = ATCPhase.LANDING_CLEARANCE
            self.phase_announced = True
    
    def request_taxi_to_gate(self):
        """User requests taxi to gate"""
        if self.phase in [ATCPhase.LANDED, ATCPhase.TAXI_IN]:
            personality = CONTROLLER_PERSONALITIES[ATCPosition.GROUND]
            msg, pos = ATCPhraseology.taxi_to_gate(self.flight_plan.callsign, personality)
            self.speak(msg, pos)
            self.phase = ATCPhase.PARKING
            self.phase_announced = True
    
    def force_phase(self, phase_name: str):
        """Force specific phase"""
        phase_map = {
            "clearance": self.request_clearance,
            "pushback": self.request_pushback,
            "taxi": self.request_taxi,
            "takeoff": self.request_takeoff,
            "climb": self.request_climb,
            "descent": self.request_descent,
            "landing": self.request_landing,
            "taxi_to_gate": self.request_taxi_to_gate
        }
        if phase_name in phase_map:
            phase_map[phase_name]()
    
    def update(self, aircraft: AircraftState):
        """Automatic phase detection and updates with frequency/airspace awareness"""
        distance_to_dest = aircraft.distance_to(self.dest_lat, self.dest_lon)
        tod_distance = self.flight_plan.get_tod_distance()
        
        # Check airspace transitions
        current_airspace, airspace_changed = self.airspace_monitor.check_airspace(aircraft)
        if airspace_changed:
            entry_msg = self.airspace_monitor.get_entry_message(current_airspace, 
                                                                self.flight_plan.callsign)
            if entry_msg:
                self.speak(entry_msg, ATCPosition.CENTER)
        
        # Check for frequency handoffs
        next_sector = self.frequency_manager.check_handoff_needed(aircraft)
        if next_sector and next_sector != self.frequency_manager.active_sector:
            # Issue handoff instruction
            msg, pos = ATCPhraseology.frequency_handoff(
                self.flight_plan.callsign,
                next_sector.name,
                next_sector.frequency,
                self.current_personality
            )
            current_pos = self.frequency_manager.active_sector.position if self.frequency_manager.active_sector else ATCPosition.CENTER
            self.speak(msg, current_pos)
            
            # Auto-switch frequency
            time.sleep(2)
            self.frequency_manager.set_active_frequency(next_sector.frequency)
            self.current_personality = next_sector.personality
            
            # Check-in with new controller
            msg, pos = ATCPhraseology.check_in_response(
                self.flight_plan.callsign,
                self.flight_plan.cruise_altitude_fl,
                next_sector.personality
            )
            time.sleep(1)
            self.speak(msg, next_sector.position)
        
        # Original auto-advance logic
        if self.phase == ATCPhase.TAKEOFF_CLEARANCE and aircraft.altitude_agl > TAKEOFF_ALTITUDE:
            if not self.phase_announced:
                msg, pos = ATCPhraseology.contact_departure(self.flight_plan.callsign,
                                                            self.frequencies['departure'])
                self.speak(msg, pos)
                self.phase = ATCPhase.DEPARTURE
                self.phase_announced = True
        
        elif self.phase == ATCPhase.DEPARTURE and aircraft.altitude_agl > INITIAL_CLIMB_ALTITUDE:
            if not self.phase_announced:
                msg, pos = ATCPhraseology.climb_clearance(self.flight_plan.callsign,
                                                          self.flight_plan.cruise_altitude_fl,
                                                          self.current_personality)
                self.speak(msg, pos)
                self.phase = ATCPhase.CLIMB
                self.phase_announced = True
        
        elif self.phase == ATCPhase.CLIMB and aircraft.altitude_msl > self.flight_plan.cruise_altitude - 1000:
            self.phase = ATCPhase.CRUISE
            self.phase_announced = False
        
        elif self.phase == ATCPhase.CRUISE:
            if not self.cruise_check_done:
                time.sleep(5)
                msg, pos = ATCPhraseology.cruise_check(self.flight_plan.callsign,
                                                       self.flight_plan.cruise_altitude_fl,
                                                       self.current_personality)
                self.speak(msg, pos)
                self.cruise_check_done = True
            
            if distance_to_dest <= tod_distance and not self.tod_announced:
                msg, pos = ATCPhraseology.top_of_descent(self.flight_plan.callsign,
                                                         int(distance_to_dest),
                                                         self.current_personality)
                self.speak(msg, pos)
                self.tod_announced = True
                self.phase = ATCPhase.TOD_ADVISORY
                self.phase_announced = False
        
        elif self.phase == ATCPhase.DESCENT:
            if self.descent_step == 1 and aircraft.altitude_msl < 29000:
                msg, pos = ATCPhraseology.descent_clearance(self.flight_plan.callsign, 18000,
                                                           self.current_personality)
                self.speak(msg, pos)
                self.descent_step = 2
            elif self.descent_step == 2 and aircraft.altitude_msl < 19000:
                msg, pos = ATCPhraseology.expect_star(self.flight_plan.callsign,
                                                      self.flight_plan.star,
                                                      self.flight_plan.arrival_runway,
                                                      self.current_personality)
                self.speak(msg, pos)
                self.descent_step = 3
            elif self.descent_step == 3 and aircraft.altitude_msl < APPROACH_ALTITUDE:
                msg, pos = ATCPhraseology.approach_clearance(self.flight_plan.callsign,
                                                             self.flight_plan.arrival_runway,
                                                             self.current_personality)
                self.speak(msg, pos)
                self.phase = ATCPhase.APPROACH
                self.phase_announced = True
        
        elif self.phase == ATCPhase.APPROACH and aircraft.altitude_msl < FINAL_APPROACH_ALTITUDE:
            if not self.phase_announced:
                msg, pos = ATCPhraseology.contact_tower(self.flight_plan.callsign,
                                                        self.frequencies['tower'],
                                                        self.current_personality)
                self.speak(msg, pos)
                self.phase = ATCPhase.FINAL_APPROACH
                self.phase_announced = True
        
        elif self.phase == ATCPhase.LANDING_CLEARANCE:
            if aircraft.on_ground and aircraft.groundspeed < LANDING_SPEED:
                msg, pos = ATCPhraseology.exit_runway(self.flight_plan.callsign,
                                                     self.current_personality)
                self.speak(msg, pos)
                self.phase = ATCPhase.LANDED
                self.phase_announced = True

# ============================================================================
# MSFS-STYLE ATC GUI
# ============================================================================

class ATCGUI:
    """Main MSFS-style ATC control panel"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("MSFS ATC Control Panel")
        self.root.geometry("1200x800")
        self.root.configure(bg=COLOR_BG)
        
        self.tts = TTSManager()
        self.flight_plan = None
        self.atc_controller = None
        self.sim_interface = None
        self.running = False
        
        self.setup_ui()
        self.load_flight_plan()
    
    def setup_ui(self):
        """Setup MSFS-style UI"""
        # Main container
        main_frame = tk.Frame(self.root, bg=COLOR_BG)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Left panel - ATC Commands
        left_panel = tk.Frame(main_frame, bg=COLOR_PANEL, relief=tk.RAISED, bd=2)
        left_panel.pack(side=tk.LEFT, fill=tk.BOTH, padx=5, pady=5)
        
        tk.Label(left_panel, text="ATC COMMANDS", bg=COLOR_PANEL, fg=COLOR_ACCENT,
                 font=('Arial', 12, 'bold')).pack(pady=10)
        
        # ATC command buttons
        commands = [
            ("Request IFR Clearance", self.cmd_clearance),
            ("Request Pushback", self.cmd_pushback),
            ("Request Taxi to Runway", self.cmd_taxi),
            ("Request Takeoff Clearance", self.cmd_takeoff),
            ("Request Climb", self.cmd_climb),
            ("Request Cruise Alt Change", self.cmd_cruise_change),
            ("Request Descent", self.cmd_descent),
            ("Request Landing Clearance", self.cmd_landing),
            ("Request Taxi to Gate", self.cmd_taxi_gate)
        ]
        
        self.cmd_buttons = {}
        for text, command in commands:
            btn = tk.Button(left_panel, text=text, command=command,
                           bg=COLOR_ACCENT, fg=COLOR_TEXT, font=('Arial', 10),
                           width=25, height=2, relief=tk.RAISED, bd=3,
                           activebackground=COLOR_SUCCESS)
            btn.pack(pady=5, padx=10)
            self.cmd_buttons[text] = btn
        
        # Force menu separator
        tk.Label(left_panel, text="FORCE CLEARANCES", bg=COLOR_PANEL,
                 fg=COLOR_WARNING, font=('Arial', 10, 'bold')).pack(pady=15)
        
        force_commands = [
            ("Force Pushback", lambda: self.force_cmd("pushback")),
            ("Force Takeoff", lambda: self.force_cmd("takeoff")),
            ("Force Descent", lambda: self.force_cmd("descent")),
            ("Force Landing", lambda: self.force_cmd("landing"))
        ]
        
        for text, command in force_commands:
            btn = tk.Button(left_panel, text=text, command=command,
                           bg=COLOR_WARNING, fg=COLOR_BG, font=('Arial', 9),
                           width=25, height=1, relief=tk.RAISED, bd=2)
            btn.pack(pady=3, padx=10)
        
        # Right panel - Status and Messages
        right_panel = tk.Frame(main_frame, bg=COLOR_BG)
        right_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=5)
        
        # Flight info panel
        info_frame = tk.Frame(right_panel, bg=COLOR_PANEL, relief=tk.RAISED, bd=2)
        info_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(info_frame, text="FLIGHT INFORMATION", bg=COLOR_PANEL,
                 fg=COLOR_ACCENT, font=('Arial', 11, 'bold')).pack(pady=5)
        
        self.flight_info_label = tk.Label(info_frame, text="Loading...",
                                          bg=COLOR_PANEL, fg=COLOR_TEXT,
                                          font=('Courier', 9), justify=tk.LEFT)
        self.flight_info_label.pack(pady=5, padx=10)
        
        # Current phase panel
        phase_frame = tk.Frame(right_panel, bg=COLOR_PANEL, relief=tk.RAISED, bd=2)
        phase_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(phase_frame, text="CURRENT PHASE & AIRSPACE", bg=COLOR_PANEL,
                 fg=COLOR_ACCENT, font=('Arial', 11, 'bold')).pack(pady=5)
        
        self.phase_label = tk.Label(phase_frame, text="Cold & Dark",
                                    bg=COLOR_PANEL, fg=COLOR_SUCCESS,
                                    font=('Arial', 16, 'bold'))
        self.phase_label.pack(pady=5)
        
        self.airspace_label = tk.Label(phase_frame, text="Airspace: Class G",
                                       bg=COLOR_PANEL, fg=COLOR_TEXT,
                                       font=('Arial', 10))
        self.airspace_label.pack(pady=2)
        
        # Aircraft state panel
        state_frame = tk.Frame(right_panel, bg=COLOR_PANEL, relief=tk.RAISED, bd=2)
        state_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(state_frame, text="AIRCRAFT STATE", bg=COLOR_PANEL,
                 fg=COLOR_ACCENT, font=('Arial', 11, 'bold')).pack(pady=5)
        
        self.aircraft_state_label = tk.Label(state_frame, text="Waiting for connection...",
                                             bg=COLOR_PANEL, fg=COLOR_TEXT,
                                             font=('Courier', 9), justify=tk.LEFT)
        self.aircraft_state_label.pack(pady=5, padx=10)
        
        # Active frequency and controller info
        freq_frame = tk.Frame(right_panel, bg=COLOR_PANEL, relief=tk.RAISED, bd=2)
        freq_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(freq_frame, text="ACTIVE CONTROLLER & FREQUENCY", bg=COLOR_PANEL,
                 fg=COLOR_ACCENT, font=('Arial', 11, 'bold')).pack(pady=5)
        
        self.controller_name_label = tk.Label(freq_frame, text="Controller: ---",
                                              bg=COLOR_PANEL, fg=COLOR_TEXT,
                                              font=('Courier', 9, 'bold'))
        self.controller_name_label.pack(pady=2)
        
        self.freq_squawk_label = tk.Label(freq_frame, text="Freq: --- | Squawk: ----",
                                          bg=COLOR_PANEL, fg=COLOR_TEXT,
                                          font=('Courier', 10, 'bold'))
        self.freq_squawk_label.pack(pady=2)
        
        self.controller_personality_label = tk.Label(freq_frame, text="Personality: ---",
                                                     bg=COLOR_PANEL, fg=COLOR_TEXT,
                                                     font=('Courier', 8))
        self.controller_personality_label.pack(pady=2)
        
        # ATC messages log
        msg_frame = tk.Frame(right_panel, bg=COLOR_PANEL, relief=tk.RAISED, bd=2)
        msg_frame.pack(fill=tk.BOTH, expand=True, pady=5)
        
        tk.Label(msg_frame, text="ATC COMMUNICATIONS", bg=COLOR_PANEL,
                 fg=COLOR_ACCENT, font=('Arial', 11, 'bold')).pack(pady=5)
        
        self.atc_log = scrolledtext.ScrolledText(msg_frame, wrap=tk.WORD,
                                                  font=('Courier', 9),
                                                  bg='#0a0a0a', fg='#00ff00',
                                                  height=12)
        self.atc_log.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.atc_log.config(state=tk.DISABLED)
        
        # Control buttons at bottom
        control_frame = tk.Frame(right_panel, bg=COLOR_BG)
        control_frame.pack(fill=tk.X, pady=5)
        
        self.start_btn = tk.Button(control_frame, text="START ATC SYSTEM",
                                   command=self.start_atc, bg=COLOR_SUCCESS,
                                   fg=COLOR_BG, font=('Arial', 11, 'bold'),
                                   height=2, relief=tk.RAISED, bd=3)
        self.start_btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)
        
        self.stop_btn = tk.Button(control_frame, text="STOP ATC SYSTEM",
                                  command=self.stop_atc, bg=COLOR_ERROR,
                                  fg=COLOR_TEXT, font=('Arial', 11, 'bold'),
                                  height=2, state=tk.DISABLED, relief=tk.RAISED, bd=3)
        self.stop_btn.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=5)
    
    def load_flight_plan(self):
        """Load flight plan"""
        self.log_message("=" * 60)
        self.log_message("MSFS ATC CONTROL PANEL - INITIALIZING")
        self.log_message("=" * 60)
        self.log_message("Loading flight plan from SimBrief...")
        
        fp = SimBriefImporter.fetch_flight_plan(SIMBRIEF_USERNAME)
        if not fp:
            self.log_message("SimBrief unavailable - using demo flight plan")
            fp = SimBriefImporter.create_demo_flight_plan()
        else:
            self.log_message("Flight plan loaded from SimBrief successfully")
        
        self.flight_plan = fp
        
        # Update flight info display
        info_text = (f"Callsign: {fp.callsign}\n"
                    f"Route: {fp.departure_icao}/{fp.departure_runway} -> "
                    f"{fp.arrival_icao}/{fp.arrival_runway}\n"
                    f"Cruise: FL{fp.cruise_altitude_fl} | Distance: {fp.distance_nm:.0f}nm\n"
                    f"Squawk: {fp.squawk}")
        self.flight_info_label.config(text=info_text)
        
        self.log_message(f"Callsign: {fp.callsign}")
        self.log_message(f"Departure: {fp.departure_icao} Runway {fp.departure_runway}")
        self.log_message(f"Arrival: {fp.arrival_icao} Runway {fp.arrival_runway}")
        self.log_message(f"Squawk Code: {fp.squawk}")
        self.log_message("")
        self.log_message("Ready. Click START ATC SYSTEM to begin.")
    
    def log_message(self, message: str, position: ATCPosition = None):
        """Add message to ATC log"""
        self.atc_log.config(state=tk.NORMAL)
        timestamp = time.strftime("%H:%M:%S")
        
        if position:
            prefix = f"[{timestamp}] [{position.value.upper():>9}] "
        else:
            prefix = f"[{timestamp}] "
        
        self.atc_log.insert(tk.END, prefix + message + "\n")
        self.atc_log.see(tk.END)
        self.atc_log.config(state=tk.DISABLED)
    
    def atc_callback(self, message: str, position: ATCPosition, phase: ATCPhase):
        """Callback from ATC controller"""
        self.log_message(message, position)
        self.phase_label.config(text=phase.value)
        
        # Update airspace display
        if self.atc_controller:
            current_airspace = self.atc_controller.airspace_monitor.current_airspace
            self.airspace_label.config(text=f"Airspace: {current_airspace.value}")
        
        # Update active controller info
        if self.atc_controller:
            controller_name, freq, personality_desc = self.atc_controller.get_active_controller_info()
            self.controller_name_label.config(text=f"Controller: {controller_name}")
            self.freq_squawk_label.config(
                text=f"Freq: {freq} | Squawk: {self.flight_plan.squawk}"
            )
            self.controller_personality_label.config(text=f"{personality_desc}")
    
    def start_atc(self):
        """Start ATC system"""
        if self.running:
            return
        
        self.log_message("=" * 60)
        self.log_message("STARTING ATC SYSTEM...")
        
        # Connect to MSFS
        self.sim_interface = SimConnectInterface()
        if not self.sim_interface.connect():
            self.log_message("WARNING: SimConnect not available - demo mode")
        else:
            self.log_message("Connected to Microsoft Flight Simulator")
        
        # Initialize ATC controller
        self.atc_controller = ATCController(self.flight_plan, self.tts, self.atc_callback)
        
        self.running = True
        self.start_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        
        self.log_message("ATC system active - use command buttons")
        self.log_message("=" * 60)
        self.log_message("")
        
        # Start monitoring
        self.monitor_flight()
    
    def stop_atc(self):
        """Stop ATC system"""
        if not self.running:
            return
        
        self.running = False
        self.log_message("")
        self.log_message("=" * 60)
        self.log_message("STOPPING ATC SYSTEM...")
        
        if self.sim_interface:
            self.sim_interface.disconnect()
            self.log_message("Disconnected from MSFS")
        
        self.start_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.log_message("ATC system stopped")
        self.log_message("=" * 60)
    
    def monitor_flight(self):
        """Monitor flight state"""
        if not self.running:
            return
        
        if self.sim_interface and self.sim_interface.connected:
            aircraft = self.sim_interface.get_aircraft_state()
            
            if aircraft:
                dist = aircraft.distance_to(self.atc_controller.dest_lat,
                                           self.atc_controller.dest_lon)
                
                # Update airspace display
                current_airspace = self.atc_controller.airspace_monitor.current_airspace
                airspace_text = f"Airspace: {current_airspace.value}"
                self.airspace_label.config(text=airspace_text)
                
                # Update controller info
                controller_name, freq, personality_desc = self.atc_controller.get_active_controller_info()
                self.controller_name_label.config(text=f"Controller: {controller_name}")
                self.freq_squawk_label.config(
                    text=f"Freq: {freq} | Squawk: {self.flight_plan.squawk}"
                )
                self.controller_personality_label.config(text=f"{personality_desc}")
                
                state_text = (f"Altitude: {int(aircraft.altitude_msl):,}ft MSL / "
                             f"{int(aircraft.altitude_agl):,}ft AGL\n"
                             f"Speed: {aircraft.groundspeed}kts | Heading: {aircraft.heading:03d}°\n"
                             f"V/S: {int(aircraft.vertical_speed):+,}fpm | Dist: {dist:.1f}nm\n"
                             f"Status: {'On Ground' if aircraft.on_ground else 'Airborne'}")
                self.aircraft_state_label.config(text=state_text)
                
                # Update ATC controller
                self.atc_controller.update(aircraft)
        
        if self.running:
            self.root.after(int(POLL_INTERVAL * 1000), self.monitor_flight)
    
    # Command button handlers
    def cmd_clearance(self):
        if self.atc_controller:
            self.atc_controller.request_clearance()
    
    def cmd_pushback(self):
        if self.atc_controller:
            self.atc_controller.request_pushback()
    
    def cmd_taxi(self):
        if self.atc_controller:
            self.atc_controller.request_taxi()
    
    def cmd_takeoff(self):
        if self.atc_controller:
            self.atc_controller.request_takeoff()
    
    def cmd_climb(self):
        if self.atc_controller:
            self.atc_controller.request_climb()
    
    def cmd_cruise_change(self):
        if self.atc_controller:
            self.atc_controller.request_cruise_altitude_change()
    
    def cmd_descent(self):
        if self.atc_controller:
            self.atc_controller.request_descent()
    
    def cmd_landing(self):
        if self.atc_controller:
            self.atc_controller.request_landing()
    
    def cmd_taxi_gate(self):
        if self.atc_controller:
            self.atc_controller.request_taxi_to_gate()
    
    def force_cmd(self, command: str):
        if self.atc_controller:
            self.atc_controller.force_phase(command)
            self.log_message(f"FORCED: {command.upper()} clearance")
    
    def on_closing(self):
        """Handle window close"""
        self.stop_atc()
        self.root.destroy()

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main application entry point"""
    root = tk.Tk()
    app = ATCGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()

if __name__ == "__main__":
    main()