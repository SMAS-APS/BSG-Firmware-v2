# Decodifica dei protocolli Bresser

Il decoder 5-in-1 nativo in `native/bresser_native/bresser_decoder.cpp` rimane
invariato. Le estensioni MicroPython in `modules/bresser_protocols.py` adattano
i formati e gli algoritmi di
[BresserWeatherSensorReceiver](https://github.com/matthias-bs/BresserWeatherSensorReceiver),
in particolare `src/WeatherSensorDecoders.cpp` e `src/WeatherSensor.cpp`.
I vettori RF 6-in-1 e 7-in-1 dei test sono tratti da
[SensorTransmitter](https://github.com/matthias-bs/SensorTransmitter),
`SensorTransmitter.ino`.

I progetti citati attribuiscono le precedenti analisi dei protocolli a rtl_433,
Sean Siford e Jorge Navarro-Ortiz. L'identificazione riguarda la famiglia
radio e il tipo del sensore; il pacchetto non identifica necessariamente il
codice commerciale della console.

## MIT License — codice di riferimento

Copyright (c) 2026 Matthias Prinke

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
