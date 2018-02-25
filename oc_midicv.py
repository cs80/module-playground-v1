# Old Crow's MIDICV with CC in CircuitPython
# 20 FEB 2018 21:46

import digitalio
import audioio
import board
import time
import busio
import adafruit_ssd1306
import analogio
from adafruit_waveform import sine

# Create 440Hz sine tone sample and assign to feather's DAC
FREQUENCY = 440    # 440 Hz middle 'A'
SAMPLERATE = 8000  # 8000 samples/second, recommended!
wave = sine.sine_wave(SAMPLERATE, FREQUENCY)
a440 = audioio.AudioOut(board.A0, wave)
a440.frequency = SAMPLERATE

# Initialize MIDI engine states
midiRunningStatus = 0
midiState = 0
midiNoteBufferIndex = 0
midiNoteBuffer = [128, 128, 128, 128, 128, 128, 128, 128, 128, 128]
midiNoteToRemove = 255

# Set up MCP4922 dual DAC
daccs = digitalio.DigitalInOut(board.A5)  # A5 is DAC CS
spi = busio.SPI(board.SCK, board.MOSI)
from adafruit_bus_device.spi_device import SPIDevice
mcp4922 = SPIDevice(spi, daccs, baudrate=8000000, polarity=0, phase=0)

# Initialize knob stuff
cclist = ['Modwheel', 'Breathctrl', 'Aftertouch', 'Velocity']
cvi = [128, 128, 128]
mux = 0

pot = [analogio.AnalogIn(board.A1),
       analogio.AnalogIn(board.A2),
       analogio.AnalogIn(board.A3)]
for i in range(0, 3):
    cvi[i] = pot[i].value
# Normalize current panel settings
midiChan = cvi[0] >> 12 # Channel in range 0~15
midiCC = cvi[1] >> 14 # CC type in range 0~3
cvaAtten = (cvi[2] * 101) // 65536 # CVA attenuate 0~100%

# Set up serial port for MIDI
ser = busio.UART(board.D1, board.D0, baudrate=31250, timeout=1)

# Toggle switch used for 'set/run' to change parameters
switch = digitalio.DigitalInOut(board.D10)
switch.direction = digitalio.Direction.INPUT
switch.pull = digitalio.Pull.UP
swToggledRun = True # Init swa latch

# Pushbutton A used for toggling 440Hz tuning note
pba = digitalio.DigitalInOut(board.D5)
pba.direction = digitalio.Direction.INPUT
pba.pull = digitalio.Pull.UP
pbaState = 1
pbaToggle = 0

# Pushbutton B used for MIDI panic/all notes off
pbb = digitalio.DigitalInOut(board.D6)
pbb.direction = digitalio.Direction.INPUT
pbb.pull = digitalio.Pull.UP
panicPressed = True # Init pbb latch

# D13 used for gate LED, A4 for gate signal
gateLED = digitalio.DigitalInOut(board.D13)
gateLED.direction = digitalio.Direction.OUTPUT
gate = digitalio.DigitalInOut(board.A4)
gate.direction = digitalio.Direction.OUTPUT

# OLED uses i2c at address 0x3C
i2c = busio.I2C(board.SCL, board.SDA)
try:
    oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3c)
    gotOLED = True
except:
    gotOLED = False

if gotOLED: # Splash screen
    oled.fill(0)
    oled.text('Old Crow\'s', 20, 8)
    oled.text('Module', 36, 18)
    oled.text('Playground:', 20, 28)
    oled.text('cktPython MIDICV', 0, 48)
    oled.show()
    time.sleep(2)

# Flush the midiNoteBuffer, used by MIDI controller code 123 (all notes off) as
# well as initialization. Gate is set to inactive.
def clearMidiNoteBuffer():
    global midiNoteBuffer
    global midiNoteToRemove
    global midiNoteBufferIndex
    for i in range(0, 10):
        midiNoteBuffer[i] = 128
    midiNoteBufferIndex = 0
    midiNoteToRemove = 255
    gate.value = 0
    gateLED.value = 0

# Called at the end of processing MIDI note off messages to
# repack the midiNoteBuffer
def compactMidiNoteBuffer():
    global midiNoteBuffer
    global midiNoteToRemove
    global midiNoteBufferIndex
    for i in range(1, 9):
        if midiNoteBuffer[i] == midiNoteToRemove:  # Maintain midiNoteBuffer
            midiNoteBuffer[i] = 128    # Clear note entry
            midiNoteToRemove = 255     # Unflag the now-removed note
            midiNoteBufferIndex -= 1   # Shrink filled buffer count

        if midiNoteBuffer[i] == 128:   # If current buffer location empty
            midiNoteBuffer[i] = midiNoteBuffer[i + 1]  # compact buffer
            midiNoteBuffer[i + 1] = 128  # justify with "slot empty" value

# Output on DAC channel 1 (half-scale)
def outputCV1(val, att):
    # 0x3xxx is DAC channel 1, gain=1x, no vref buffer, output active
    val = (val * att) // 100
    dacData = bytearray(2)
    dacData[0] = ((val >> 3) & 0x0F) | 0x30
    dacData[1] = (val << 5) & 0xF0
    with mcp4922:
        spi.write(dacData)

# Output on DAC channel 2
def outputCV2(note):
    while note > 84:
        note -= 12  # Wrap notes above C6 to highest usable octave
    while note < 24:
        note += 12  # Wrap notes below C1 to lowest usable octave
    x = (note - 24) * 273  # Magic formula for semitone scale (n-t)*4095/60
    y = (x >> 2) + ((x >> 1) & 1)  # Round for 0.5 LSB accuracy
    # 0xBxxx is DAC channel 2, gain=1x, no vref buffer, output active
    dacData = bytearray(2)
    dacData[0] = ((y >> 8) & 0x0F) | 0xB0
    dacData[1] = y & 0xFF
    with mcp4922:
        spi.write(dacData)

def handleNoteOn(note, val):
    global midiNoteBufferIndex
    global midiNoteBuffer
    global midiNoteToRemove
    global midiNoteLegato
    if val != 0:
        midiNoteBufferIndex += 1
        midiNoteBuffer[midiNoteBufferIndex] = note  # Add newest note to buffer
        outputCV2(note)  # Send to DAC
        gate.value = 1  # Gate high
        gateLED.value = 1
        if midiCC == 3: # Use key velocity if selected for CVA
            outputCV1(val, cvaAtten)
        if midiNoteBufferIndex == 9:  # Buffer full? Limit to 8 notes
            midiNoteBuffer[1] == 128  # Flag oldest entry for removal
            midiNoteBufferIndex -= 1  # Back out to 8th entry
    else:  # Velocity zero note off
        handleNoteOff(note)

def handleNoteOff(note):
    global midiNoteBufferIndex
    global midiNoteBuffer
    global midiNoteToRemove
    global midiNoteLegato
    midiNoteToRemove = note  # Flag note to clear from buffer
    # If current note is to be turned off
    if midiNoteBuffer[midiNoteBufferIndex] == midiNoteToRemove:
        # Then provided buffer is not empty
        if midiNoteBufferIndex > 0:
            # and it is not the only note playing
            if (midiNoteBufferIndex - 1) > 0:
                # play the previous note
                midiNoteLegato = midiNoteBuffer[midiNoteBufferIndex - 1]
                outputCV2(midiNoteLegato)  # legato-style (no retrigger)
    compactMidiNoteBuffer()  # Manage note buffer

def handleMidiCC(cc, val):
    if cc == 123 and val == 0:
        clearMidiNoteBuffer()
        return
    if cc == midiCC + 1:
        outputCV1(val, cvaAtten)
        return

def doMIDI(mrx: bytes):
    global midiRunningStatus
    global midiState
    global midiNote
    global midiVel
    global midiChan
    if mrx > 0xEF and mrx < 0xF8:  # ignore mode messages
        midiRunningStatus = 0
        midiState = 0
        return

    if mrx > 0xF7:
        return  # bail on realtime leaving previous status

    if mrx & 0x80:  # got a command byte
        midiRunningStatus = mrx
        midiRcvChan = midiRunningStatus & 0x0F
        if midiRcvChan == midiChan:  # Check channel number
            midiState = 1
        else:
            midiRunningStatus = 0
            midiState = 0
        return

    if mrx < 0x80:  # if data byte assign it
        if not midiRunningStatus:
            return

        if midiState == 1:
            midiNote = mrx  # got a note value
            if midiRunningStatus > 0xBF and midiRunningStatus < 0xE0:
                midiState = 1 #  For 2-byte messages
                midiVel = 0
            else:
                midiState = 2 #  For 3-byte messages
                return

        if midiState == 2:
            midiVel = mrx  # got a velocity value
            midiState = 1

        if midiRunningStatus == 0x90: # Note on
            handleNoteOn(midiNote, midiVel)
            return

        if midiRunningStatus == 0x80: # Note off
            handleNoteOff(midiNote)
            return

        if (midiRunningStatus == 0xB0) and (midiCC < 2): # CC
            handleMidiCC(midiNote, midiVel) #  controller, data
            return

        if (midiRunningStatus == 0xD0) and (midiCC == 2): # AT
            handleMidiCC(3, midiNote) #  1st data is AT
            
def updateOLED(mode, cc, atten):
    oled.fill(0)
    mode = 'MIDICV: ' + mode
    cctype = 'CVA: ' + cclist[cc]
    atten = 'CVA level: ' + str(atten) + '%'
    oled.text('<CircuitPython!>', 0, 0, 1)
    oled.text(mode, 0, 20, 1)
    oled.text('MIDI channel: %d' % midiChan, 0, 30, 1)
    oled.text(cctype, 0, 40, 1)
    oled.text(atten, 0, 50, 1)
    oled.show()

while True:
    # Read the 3 pots one at a time
    # Exponentially-weighted sample averaging
    cvi[mux] += (pot[mux].value - cvi[mux]) >> 2
    mux += 1
    if mux > 2:
        mux = 0

    if switch.value: # "set" mode
        midiChan = cvi[0] >> 12 # Channel in range 0~15
        midiCC = cvi[1] >> 14 # CC type in range 0~3
        cvaAtten = (cvi[2] * 101) // 65536 #  1% steps for CVA fullscale
        swToggledRun = True
        if gotOLED:
            if pbaToggle:
                updateOLED('A440', midiCC, cvaAtten)
            else:
                updateOLED('SET', midiCC, cvaAtten)
        # Panic button (PBB) to clear stuck notes
        if not pbb.value and panicPressed:
            handleMidiCC(123, 0) # Controller code 123 is all notes off
            panicPressed = False
        elif pbb.value and not panicPressed:
            panicPressed = True
        
    else:            # "run" mode
        if swToggledRun:
            if gotOLED:
                if pbaToggle:
                    updateOLED('A440', midiCC, cvaAtten)
                else:
                    updateOLED('RUN', midiCC, cvaAtten)
            swToggledRun = False

        midiRX = ser.read(1)
        if midiRX:
            rcv = midiRX[0]
            doMIDI(rcv)

    # Manage PBA push-to-toggle for A440
    pbaRead = pba.value
    if pbaRead != pbaState:
        pbaState = pbaRead
        if not pbaState:
            pbaToggle = not pbaToggle
            if pbaToggle:
                if gotOLED:
                    updateOLED('A440', midiCC, cvaAtten)
                a440.play(loop=True)
            else:
                if gotOLED:
                    if switch.value:
                        updateOLED('SET', midiCC, cvaAtten)
                    else:
                        updateOLED('RUN', midiCC, cvaAtten)
                a440.stop()
	
    # Release gate signal if no notes left
    if midiNoteBufferIndex == 0:
        gate.value = 0
        gateLED.value = 0

# Code end
