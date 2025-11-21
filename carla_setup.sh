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

# Check if process is still alive
if ! kill -0 "$JACK_PID" 2>/dev/null; then
    echo "? JACK crashed immediately"
    echo "--- LOG ---"
    cat "$LOG"
    exit 1
fi

# Check for known failure text in log
if grep -q "Failed to open server" "$LOG"; then
    echo "? JACK server failed to start"
    kill "$JACK_PID" 2>/dev/null
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
if [[ $1 == "online" ]]; then
    echo "Starting Flask webapp (app.py)..."

    # Clear log
    > /tmp/webapp.log

    # Start your Flask webapp
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
fi
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
jack_connect "a2j:AKM320 [24] (capture): AKM320 MIDI 1" "ADLplug:events-in"

cd ..
cd potdemo/
python pot_test.py

echo "READY TO START"

