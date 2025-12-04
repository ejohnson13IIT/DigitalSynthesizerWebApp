#!/usr/bin/env python3
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
        # Get sample rate for accurate timing
        sample_rate = self.client.samplerate
        buffer_time = frames / sample_rate  # Time duration of this buffer in seconds
        
        # Process MIDI events
        for offset, data in self.midi_in.incoming_midi_events():
            if len(data) >= 3:
                # Convert to integers
                status = int(data[0]) & 0xFF
                note = int(data[1]) & 0xFF
                velocity = int(data[2]) & 0xFF
                
                # Detect Note On events
                if (status & 0xF0) == 0x90 and velocity > 0:
                    # Calculate precise timestamp: current time + offset within buffer
                    current_time = time.perf_counter()
                    # Account for MIDI event position within the buffer
                    offset_time = (offset / sample_rate)  # Time offset within buffer
                    # Estimate when MIDI actually occurred (start of buffer processing minus offset)
                    # Since we're processing the buffer now, the MIDI happened slightly before
                    # We approximate by using current time minus the remaining buffer time
                    midi_timestamp = current_time - (buffer_time - offset_time)
                    self.midi_times.append((midi_timestamp, note))
        
        # Process audio for onset detection (always process, not just when MIDI exists)
        audio_data = self.audio_in.get_array()
        
        if len(audio_data) > 0:
            # Calculate RMS energy
            rms = np.sqrt(np.mean(audio_data**2))
            
            # Detect onset: energy rising above threshold
            if rms > self.audio_threshold and self.last_energy < self.audio_threshold:
                # Find the sample index where onset likely occurred
                # Look for the first sample that crosses threshold
                onset_sample = None
                for i in range(len(audio_data)):
                    sample_rms = abs(audio_data[i])
                    if sample_rms > self.audio_threshold:
                        onset_sample = i
                        break
                
                # Calculate precise timestamp accounting for onset position in buffer
                current_time = time.perf_counter()
                if onset_sample is not None:
                    # Audio onset happened at: current time - (remaining buffer time)
                    onset_time_in_buffer = onset_sample / sample_rate
                    audio_timestamp = current_time - (buffer_time - onset_time_in_buffer)
                else:
                    # Fallback: assume onset at start of buffer
                    audio_timestamp = current_time - buffer_time
                
                self.audio_onsets.append((audio_timestamp, rms))
                
                # Match with most recent MIDI event
                if len(self.midi_times) > 0:
                    midi_time, note = self.midi_times[0]
                    latency = audio_timestamp - midi_time
                    latency_ms = latency * 1000
                    
                    # Only record positive latencies (audio after MIDI)
                    if latency_ms > 0:
                        self.latencies.append(latency_ms)
                        self.midi_times.popleft()
                        
                        print(f"Latency: {latency_ms:.2f} ms")
                        
                        # Print running statistics every 5 measurements
                        if len(self.latencies) % 5 == 0:
                            self.print_statistics()
                    else:
                        # Negative latency means audio detected before MIDI (shouldn't happen)
                        print(f"Warning: Negative latency detected ({latency_ms:.2f} ms), skipping")
                        self.midi_times.popleft()
            
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
        """Auto-connect to MIDI input and audio output"""
        # Find AKM320 MIDI port
        try:
            midi_ports = self.client.get_ports(
                name_pattern="a2j:AKM320",
                is_midi=True,
                is_input=False
            )
            if midi_ports:
                self.client.connect(midi_ports[0], self.midi_in)
                print(f"Connected MIDI: {midi_ports[0]} -> {self.midi_in.name}")
            else:
                print("Warning: Could not find a2j:AKM320 MIDI port")
                print("   Available MIDI ports:")
                all_midi = self.client.get_ports(is_midi=True, is_input=False)
                for port in all_midi:
                    print(f"     - {port.name}")
        except Exception as e:
            print(f"Error connecting MIDI: {e}")
        
        # Connect to your plugin chain output (monitor the final audio output)
        # Try to find your final plugin output (3 Band EQ or NewProject)
        try:
            # First try to find 3 Band EQ output (your final plugin)
            eq_ports = self.client.get_ports(
                name_pattern="3 Band EQ:audio-out",
                is_midi=False,
                is_input=False
            )
            if len(eq_ports) >= 1:
                self.client.connect(eq_ports[0], self.audio_in)
                print(f"Connected Audio: {eq_ports[0]} -> {self.audio_in.name}")
            else:
                # Fallback to NewProject output
                newproject_ports = self.client.get_ports(
                    name_pattern="NewProject:audio-out",
                    is_midi=False,
                    is_input=False
                )
                if len(newproject_ports) >= 1:
                    self.client.connect(newproject_ports[0], self.audio_in)
                    print(f"Connected Audio: {newproject_ports[0]} -> {self.audio_in.name}")
                else:
                    print("Warning: Could not find plugin output ports")
                    print("   Available audio output ports:")
                    all_audio = self.client.get_ports(is_midi=False, is_input=False)
                    for port in all_audio[:10]:  # Show first 10
                        print(f"     - {port.name}")
                    print("   (showing first 10, use one of these)")
        except Exception as e:
            print(f"Error connecting audio: {e}")
            print("   You may need to manually connect:")
            print("   jack_connect <your_plugin>:audio-out_1 MIDILatencyMonitor:audio_monitor")

    def start(self):
        """Start monitoring"""
        self.client.activate()
        self.connect_ports()
        print("\n" + "="*60)
        print("MIDI to Audio Latency Monitor")
        print("="*60)
        print("Monitoring MIDI input -> Plugin audio output")
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
            print("  2. Audio is being produced by your plugin")
            print("  3. Audio connection is made to MIDILatencyMonitor:audio_monitor")
        
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
