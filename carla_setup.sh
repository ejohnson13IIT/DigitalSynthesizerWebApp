#!/bin/bash

sudo killall jackd
sudo killall a2jmidid
sudo pkill -9 python 2>/dev/null

PING_TARGET="8.8.8.8"
ATTEMPTS=3
ONLINE=false

for i in $(seq 1 $ATTEMPTS); do
    if ping -c 1 -W 2 "$PING_TARGET" >/dev/null 2>&1; then
        ONLINE=true
        break
    fi
    sleep 2
done

# Wait for audio devices to be released
sleep 2

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

if [ "$ONLINE" = true ]; then
    echo "Starting Flask webapp (app.py)..."

    # Clear log
    > /tmp/webapp.log

    # Start your Flask webapp
    cd ..
    python app.py > /tmp/webapp.log 2>&1 &
    WEB_PID=$!

    # Wait for a READY signal from app.py
    echo "Waiting for webapp to initialize..."

    while ! grep -q "WEBAPP_READY" /tmp/webapp.log; do
        if ! kill -0 $WEB_PID 2>/dev/null; then
            echo "? Webapp crashed before startup"
            cat /tmp/webapp.log
            exit 1
        fi
        sleep 0.2
    done

    echo "Webapp started successfully (PID $WEB_PID)"
    cd CarlaStartupAPI
fi

# Now run your jack_connect
# Find the AKM320 MIDI port dynamically (handles changing ALSA card numbers)
AKM320_PORT=$(jack_lsp | grep -E "a2j:AKM320 \[[0-9]+\] \(capture\): AKM320 MIDI 1" | head -n1)


echo "Connecting $AKM320_PORT to ADLplug:events-in"
jack_connect "$AKM320_PORT" "ADLplug:events-in"


cd ..
cd potdemo/
python pot_test.py &

# Wait a moment for everything to fully initialize
sleep 3

# Get the window ID from wmctrl -l and make it fullscreen
echo "Finding window and setting to fullscreen..."
echo "Available windows:"
wmctrl -l

# Get the first window ID (skip the header line if present)
WINDOW_ID=$(wmctrl -l | grep -v "^ *$" | head -n1 | awk '{print $1}')

if [ -n "$WINDOW_ID" ]; then
    echo "Using window ID: $WINDOW_ID"
    wmctrl -i -r "$WINDOW_ID" -b add,fullscreen,skip_pager,above
    echo "Window set to fullscreen"
else
    echo "Warning: Could not find any window"
fi

echo "READY TO START"

wait
