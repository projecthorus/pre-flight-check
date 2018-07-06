#!/usr/bin/env python2.7
#
#   Project Horus - Pre-Flight Check Web Interface
#
#   Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#   Released under GNU GPL v3 or later
#
import json
import flask
from flask_socketio import SocketIO
import time
import datetime
from horuslib import *
from horuslib.wenet import *
from horuslib.listener import *
from horuslib.earthmaths import *


# Define Flask Application, and allow automatic reloading of templates for dev
app = flask.Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
app.config['TEMPLATES_AUTO_RELOAD'] = True
app.jinja_env.auto_reload = True

# SocketIO instance
socketio = SocketIO(app)



# Global stores of data.

# Incoming OziMux data.
# One dictionary element will be produced per source name, and will be updated with data, and data age.
# Each entry will contain:
#   'source name'
#   'lat'
#   'lon'
#   'alt'
#   'age'
#   'timestamp'
current_ozimux = {}


# LoRa Data
current_lora = {
    'frequency': 0.0,
    'rssi': -300.0,
    'payloads': {}
}


# Do not send packets of this type to the client's 'packet sniffer' log.
LAST_PACKETS_DISCARD = ['LOWPRIORITY', 'WENET', 'OZIMUX']

#
#   Flask Routes
#

@app.route("/")
def flask_index():
    """ Render main index page """
    return flask.render_template('index.html')


@app.route("/current_lora")
def get_lora_data():
    return json.dumps(current_lora)


@app.route("/current_ozimux")
def get_ozimux():
    return json.dumps(current_ozimux)


def flask_emit_event(event_name="none", data={}):
    """ Emit a socketio event to any clients. """
    socketio.emit(event_name, data, namespace='/update_status') 


# Packet Handlers.
# These functions process data received via UDP and update the global stores of information.
def handle_wenet_packets(packet):
    ''' Handle Wenet payload specific packets '''
    packet_type = decode_wenet_packet_type(packet)

    if packet_type == WENET_PACKET_TYPES.TEXT_MESSAGE:
        _text_data = decode_text_message(packet)
        _packet_str = "Debug %d: " % _text_data['id'] + _text_data['text']
        _packet_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        flask_emit_event('wenet_event', {'timestamp':_packet_time, 'msg':_packet_str})

    elif packet_type == WENET_PACKET_TYPES.GPS_TELEMETRY:
        _gps_telem_str = gps_telemetry_string(packet)
        flask_emit_event('wenet_gps', {'data':_gps_telem_str})
 
    else:
        pass



def handle_packets(packet):
    ''' Handle received UDP packets '''
    global current_lora

    # Send a text representation of the packet to the web client.
    if packet['type'] not in LAST_PACKETS_DISCARD:
        _packet_str = " ".join(udp_packet_to_string(packet).split(" ")[1:])
        _packet_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        flask_emit_event('log_event', {'timestamp':_packet_time, 'msg':_packet_str})

    # Handle LoRa Status Messages
    if packet['type'] == 'STATUS':
        current_lora['frequency'] = packet['frequency']
        current_lora['rssi'] = float(packet['rssi'])
        # Indicate to the web client there is new data.
        flask_emit_event('lora_event', current_lora)

    # LoRa RX Packets
    elif packet['type'] == 'RXPKT':
#{u'timestamp': u'2018-07-06T10:41:17.443986', u'snr': 9.25, u'rssi': -44, u'type': u'RXPKT', u'payload': [0, 0, 1, 15, 0, 10, 41, 34, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 194, 0, 0, 67, 0], u'freq_error': -130955}
# {'uplinkSlots': 0, 'batt_voltage': 1.6411764705882352, 'second': 34, 'current_timeslot': 0, 'speed': 0, 'payload_id': 1, 'sats': 0, 
#   'altitude': 0, 'batt_voltage_raw': 194, 'payload_flags': 0, 'minute': 41, 'latitude': 0.0, 'RSSI': -97, 'rxPktCount': 0, 
#   'pyro_voltage': 0.0, 'packet_type': 0, 'used_timeslots': 0, 'seconds_in_day': 38494, 'hour': 10, 'temp': 0, 'counter': 15, 'longitude': 0.0, 'time': '10:41:34', 'pyro_voltage_raw': 0}
        payload_type = decode_payload_type(packet['payload'])
        if payload_type == HORUS_PACKET_TYPES.PAYLOAD_TELEMETRY:
            telemetry = decode_horus_payload_telemetry(packet['payload'])

            _payload_id_str = str(telemetry['payload_id'])
            if _payload_id_str not in current_lora['payloads']:
                current_lora['payloads'][_payload_id_str] = telemetry

            # Update a few fields.
            current_lora['payloads'][_payload_id_str]['pkt_rssi'] = packet['rssi']
            current_lora['payloads'][_payload_id_str]['pkt_snr'] = packet['snr']
            current_lora['payloads'][_payload_id_str] = telemetry

            # Indicate to the web client there is new data.
            flask_emit_event('lora_event',current_lora)

    elif packet['type'] == 'WENET':
        handle_wenet_packets(packet['packet'])

    elif packet['type'] == 'OZIMUX':
        # Add data to our store of ozimux data

        _src_name = packet['source_name']

        if _src_name not in current_ozimux:
            current_ozimux[_src_name] = {}

        current_ozimux[_src_name]['source'] = _src_name
        current_ozimux[_src_name]['latitude'] = packet['latitude']
        current_ozimux[_src_name]['longitude'] = packet['longitude']
        current_ozimux[_src_name]['altitude'] = packet['altitude']
        current_ozimux[_src_name]['timestamp'] = datetime.now().strftime("%H:%M:%S")

        # Indicate to the web client there is new data.
        flask_emit_event('ozimux_event',current_ozimux)

    pass


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-p","--port",default=5001,help="Port to run Web Server on.")
    args = parser.parse_args()

    horus_udp_rx = UDPListener(callback=handle_packets)
    horus_udp_rx.start() 

    # Run the Flask app, which will block until CTRL-C'd.
    socketio.run(app, host='0.0.0.0', port=args.port)

    # Attempt to close the listener.
    horus_udp_rx.close()

