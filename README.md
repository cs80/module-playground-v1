# module-playground-v1
Old Crow's Module Playground 10HP Eurorack module using the Adafruit Feather M0/M4 and CircuitPython.
Make sure the feather to be used has at least circuitpython 2.2.x installed as well as the adafruit
circuitpython libraries. See https://github.com/adafruit/circuitpython/releases and
https://learn.adafruit.com/welcome-to-circuitpython/circuitpython-libraries for more info.

For oc_midicv.py use mpy-cross and place resulting oc_midicv.mpy file in the lib folder of CIRCUITPY:
Rename init_midicv.py to code.py and place in top level of CIRCUITPY: Pre-compiled .mpy is included
here for the lazy hacker. ;)

  The example program oc_midicv.py is too large to run in the M0 memory space which is why it requires
compiling to bytecode (.mpy) to squeeze it down to fit.  mpy-cross is availabe at the circuitpython
link above.  Note that mpy-cross is a command-line utility.

25-FEB-2018 Scott Rider / The Old Crow
