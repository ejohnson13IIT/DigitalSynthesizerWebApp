"""
Measure latency from MIDI input (a2jmidid) to system playback output
"""

import jack
import time
import numpy as np
from collections import deque
from statistics import mean, stdev

class MIDIToAudioLatencyMonitor:
    def __init__(self):
        self.client = jack.Client("MIDILatencyMonitor")
        
        # Storage for timing measurements
        self.midi_times = deque(maxlen=100)  # Store (timestamp, note) tuples
        self.audio_onsets = deque(maxlen=100)  # Store (timestamp, amplitude) tuples
        self.latencies = []  # Store calculated latencies in ms
        
        # Audio processing parameters
        self.audio_threshold = 0.05  # Amplitude threshold for note detection
        self.energy_window = 512  # Samples to average for energy calculation
        self.last_energy = 0.0
        
        # Register ports
        self.midi_in = self.client.midi_inports.register("midi_monitor")
        self.audio_in = self.client.inports.register("audio_monitor")
        
        # Set up process callback
        self.client.set_process_callback(self.process)
        
        # Statistics
        self.stats_printed = False
        
    def process(self, frames):
        """Real-time audio processing callback"""
        # Process MIDI events
        for offset, data in self.midi_in.incoming_midi_events():
            if len(data) >= 3:
                status = data[0] & 0xF0
                note = data[1]
                velocity = data[2]
                
                # Detect Note On events
                if status == 0x90 and velocity > 0:
                    timestamp = time.perf_counter()
                    self.midi_times.append((timestamp, note))
                    print(f"\nMIDI Note On: {note} (vel={velocity}) at {timestamp:.6f}")
        
        # Process audio for onset detection
        if len(self.midi_times) > 0:
            audio_data = self.audio_in.get_array()
            
            if len(audio_data) > 0:
                # Calculate RMS energy
                rms = np.sqrt(np.mean(audio_data**2))
                
                # Detect onset: energy rising above threshold
                if rms > self.audio_threshold and self.last_energy < self.audio_threshold:
                    timestamp = time.perf_counter()
                    self.audio_onsets.append((timestamp, rms))
                    
                    # Match with most recent MIDI event
                    if len(self.midi_times) > 0:
                        midi_time, note = self.midi_times[0]
                        latency = timestamp - midi_time
                        latency_ms = latency * 1000
                        
                        self.latencies.append(latency_ms)
                        self.midi_times.popleft()
                        
                        print(f"?? Audio detected: RMS={rms:.4f}, Latency: {latency_ms:.2f} ms")
                        
                        # Print running statistics every 5 measurements
                        if len(self.latencies) % 5 == 0:
                            self.print_statistics()
                
                self.last_energy = rms
    
    def print_statistics(self):
        """Print current latency statistics"""
        if len(self.latencies) < 2:
            return
        
        latencies = np.array(self.latencies)
        print(f"\nStatistics ({len(self.latencies)} measurements):")
        print(f"   Min:    {np.min(latencies):.2f} ms")
        print(f"   Max:    {np.max(latencies):.2f} ms")
        print(f"   Mean:   {np.mean(latencies):.2f} ms")
        print(f"   StdDev: {np.std(latencies):.2f} ms")
        print(f"   Median: {np.median(latencies):.2f} ms")
    
    def connect_ports(self):
        """Auto-connect to MIDI input and system playback"""
        # Find AKM320 MIDI port
        try:
            midi_ports = self.client.get_ports(
                name_pattern="a2j:AKM320",
                is_midi=True,
                is_input=False
            )
            if midi_ports:
                self.client.connect(midi_ports[0], self.midi_in)
                print(f"? Connected MIDI: {midi_ports[0]} -> {self.midi_in.name}")
            else:
                print("? Warning: Could not find a2j:AKM320 MIDI port")
                print("   Available MIDI ports:")
                all_midi = self.client.get_ports(is_midi=True, is_input=False)
                for port in all_midi:
                    print(f"     - {port.name}")
        except Exception as e:
            print(f"Error connecting MIDI: {e}")
        
        # Connect to system playback (monitor what's being sent to speakers)
        try:
            playback_ports = self.client.get_ports(
                name_pattern="system:playback",
                is_midi=False,
                is_input=True
            )
            if len(playback_ports) >= 1:
                self.client.connect(playback_ports[0], self.audio_in)
                print(f"? Connected Audio: {playback_ports[0]} -> {self.audio_in.name}")
            else:
                print("? Warning: Could not find system:playback ports")
        except Exception as e:
            print(f"? Error connecting audio: {e}")
    
    def start(self):
        """Start monitoring"""
        self.client.activate()
        self.connect_ports()
        print("\n" + "="*60)
        print("MIDI to Audio Latency Monitor")
        print("="*60)
        print("Monitoring MIDI input -> System playback")
        print("Play MIDI notes to measure latency...")
        print("Press Ctrl+C to stop and see final statistics")
        print("="*60 + "\n")
    
    def stop(self):
        """Stop monitoring and print final statistics"""
        self.client.deactivate()
        self.client.close()
        
        print("\n" + "="*60)
        print("Final Statistics")
        print("="*60)
        
        if len(self.latencies) > 0:
            latencies = np.array(self.latencies)
            print(f"Total measurements: {len(self.latencies)}")
            print(f"Min latency:    {np.min(latencies):.2f} ms")
            print(f"Max latency:    {np.max(latencies):.2f} ms")
            print(f"Mean latency:   {np.mean(latencies):.2f} ms")
            print(f"Std deviation:  {np.std(latencies):.2f} ms")
            print(f"Median latency: {np.median(latencies):.2f} ms")
            
            # Percentiles
            print(f"\nPercentiles:")
            print(f"  25th: {np.percentile(latencies, 25):.2f} ms")
            print(f"  50th: {np.percentile(latencies, 50):.2f} ms")
            print(f"  75th: {np.percentile(latencies, 75):.2f} ms")
            print(f"  95th: {np.percentile(latencies, 95):.2f} ms")
            print(f"  99th: {np.percentile(latencies, 99):.2f} ms")
        else:
            print("No measurements collected.")
            print("Make sure:")
            print("  1. MIDI keyboard is connected and sending notes")
            print("  2. Audio is playing through system:playback")
            print("  3. Your plugin chain is producing audio")
        
        print("="*60)

def main():
    try:
        monitor = MIDIToAudioLatencyMonitor()
        monitor.start()
        
        # Keep running until interrupted
        while True:
            time.sleep(1)
            
    except KeyboardInterrupt:
        print("\n\nStopping monitor...")
        monitor.stop()
    except Exception as e:
        print(f"\nError: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()