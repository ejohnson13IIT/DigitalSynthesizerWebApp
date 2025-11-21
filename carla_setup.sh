#!/bin/bash

killall jackd
killall a2jmidid
pkill -9 python 2>/dev/null

LOG="/tmp/jack_startup.log"

# Clear old log
> "$LOG"

# Start JACK in background, capture stderr and stdout
jackd -dalsa -dhw:3 -r44100 -p1024 -n2 -S >"$LOG" 2>&1 &

JACK_PID=$!

# Wait up to 2 seconds to see if JACK dies or prints an error
sleep 2

# Check for known failure text in log first
if grep -q "Failed to open server" "$LOG"; then
    echo "? JACK server failed to start, trying -dhw:2..."
    kill "$JACK_PID" 2>/dev/null
    > "$LOG"
    
    # Try with -dhw:2
    jackd -dalsa -dhw:2 -r44100 -p1024 -n2 -S >"$LOG" 2>&1 &
    
    JACK_PID=$!
    
    sleep 2
    
    if ! kill -0 "$JACK_PID" 2>/dev/null; then
        echo "? JACK crashed immediately with -dhw:2"
        echo "--- LOG ---"
        cat "$LOG"
        exit 1
    fi
    
    if grep -q "Failed to open server" "$LOG"; then
        echo "? JACK server failed to start with -dhw:2"
        kill "$JACK_PID" 2>/dev/null
        exit 1
    fi
fi

# Check if process is still alive
if ! kill -0 "$JACK_PID" 2>/dev/null; then
    echo "? JACK crashed immediately"
    echo "--- LOG ---"
    cat "$LOG"
    exit 1
fi

echo "JACK started successfully (PID $JACK_PID)"

a2jmidid -e >"$LOG" 2>&1 &

a2jmidi_PID=$!

sleep 2

if ! kill -0 "$a2jmidi_PID" 2>/dev/null; then
	echo "A2JMIDI crashed immediately"
	echo "--- LOG ---"
	cat "$LOG"
	exit 1
fi

echo "A2JMIDI Started Successfully (PID $a2jmidi_PID)"

source venv/bin/activate
cd CarlaStartupAPI
python carla_startup.py > /tmp/carla_boot.log 2>&1 &
PY_PID=$!

echo "Waiting for python to initialize..."

# Loop until PYTHON_READY is printed
while ! grep -q "PYTHON_READY" /tmp/carla_boot.log; do
    # Also check if python crashed
    if ! kill -0 $PY_PID 2>/dev/null; then
        echo "? Python crashed before startup"
        cat /tmp/carla_boot.log
        exit 1
    fi
    sleep 0.2
done

echo "Python is ready, connecting JACK ports..."

# Now run your jack_connect
# Find the AKM320 MIDI port dynamically (handles changing ALSA card numbers)
AKM320_PORT=$(jack_lsp | grep -E "a2j:AKM320 \[[0-9]+\] \(capture\): AKM320 MIDI 1" | head -n1)


echo "Connecting $AKM320_PORT to ADLplug:events-in"
jack_connect "$AKM320_PORT" "ADLplug:events-in"


cd ..
cd potdemo/
python pot_test.py

echo "READY TO START"

