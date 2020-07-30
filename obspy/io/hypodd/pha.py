# -*- coding: utf-8 -*-
"""
HypoDD PHA read support.

:copyright:
    The ObsPy Development Team (devs@obspy.org)
:license:
    GNU Lesser General Public License, Version 3
    (https://www.gnu.org/copyleft/lesser.html)
"""
import io
from math import cos
from numpy import deg2rad
from warnings import warn

from obspy import UTCDateTime
from obspy.core.event import (
    Catalog, Event, Origin, Magnitude, Pick, WaveformStreamID, Arrival,
    OriginQuality)
from obspy.core.util.misc import _seed_id_map


DEG2KM = 111.2


def _block2event(block, seed_map, id_default, ph2comp, eventid_map):
    """
    Read HypoDD event block
    """
    lines = block.strip().splitlines()
    yr, mo, dy, hr, mn, sc, la, lo, dp, mg, eh, ez, rms, id_ = lines[0].split()
    if eventid_map is not None and id_ in eventid_map:
        id_ = eventid_map[id_]
    time = UTCDateTime(int(yr), int(mo), int(dy), int(hr), int(mn), float(sc),
                       strict=False)
    laterr = None if float(eh) == 0 else float(eh) / DEG2KM
    lonerr = (None if laterr is None or float(la) > 89 else
              laterr / cos(deg2rad(float(la))))
    ez = None if float(ez) == 0 else float(ez) * 1000
    rms = None if float(rms) == 0 else float(rms)
    picks = []
    arrivals = []
    for line in lines[1:]:
        sta, reltime, weight, phase = line.split()
        comp = ph2comp.get(phase, '')
        wid = seed_map.get(sta, id_default)
        _waveform_id = WaveformStreamID(seed_string=wid.format(sta, comp))
        pick = Pick(waveform_id=_waveform_id, phase_hint=phase,
                    time=time + float(reltime))
        arrival = Arrival(phase=phase, pick_id=pick.resource_id,
                          time_weight=float(weight))
        picks.append(pick)
        arrivals.append(arrival)
    qu = OriginQuality(associated_phase_count=len(picks), standard_error=rms)
    origin = Origin(arrivals=arrivals,
                    resource_id="smi:local/origin/" + id_,
                    quality=qu,
                    latitude=float(la),
                    longitude=float(lo),
                    depth=1000 * float(dp),
                    latitude_errors=laterr,
                    longitude_errors=lonerr,
                    depth_errors=ez,
                    time=time)
    if mg.lower() == 'nan':
        magnitudes = []
        preferred_magnitude_id = None
    else:
        magnitude = Magnitude(mag=mg, resource_id="smi:local/magnitude/" + id_)
        magnitudes = [magnitude]
        preferred_magnitude_id = magnitude.resource_id
    event = Event(resource_id="smi:local/event/" + id_,
                  picks=picks,
                  origins=[origin],
                  magnitudes=magnitudes,
                  preferred_origin_id=origin.resource_id,
                  preferred_magnitude_id=preferred_magnitude_id)
    return event


def _is_pha(filename):
    try:
        with open(filename, 'rb') as f:
            line = f.readline()
        assert line.startswith(b'#')
        assert len(line.split()) == 15
        yr, mo, dy, hr, mn, sc = line.split()[1:7]
        UTCDateTime(int(yr), int(mo), int(dy), int(hr), int(mn), float(sc),
                    strict=False)
    except Exception:
        return False
    else:
        return True


def _read_pha(filename, inventory=None, id_map=None, id_default='.{}..{}',
              ph2comp={'P': 'Z', 'S': 'N'}, eventid_map=None,
              encoding='utf-8'):
    """
    Read a HypoDD PHA file and returns an ObsPy Catalog object.

    .. warning::
        This function should NOT be called directly, it registers via the
        ObsPy :func:`~obspy.core.event.read_events` function, call this
        instead.

    The optional parameters all deal with the problem, that the PHA format
    only stores station names for the picks, but the Pick object expects
    a SEED id. A SEED id template is retrieved for each station by the
    following procedure:

    1. look at id_map for a direct station name match and use the specified
       template
    2. if 1 did not succeed, look if the station is present in inventory and
       use its first channel as template
    3. if 1 and 2 did not succeed, use specified default template (id_default)

    :param str filename: File or file-like object in text mode.
    :type inventory: :class:`~obspy.core.inventory.inventory.Inventory`
    :param inventory: Inventory used to retrieve network code, location code
        and channel code of stations (SEED id).
    :param dict id_map: Default templates for each station
        (example: `id_map={'MOX': 'GR.{}..HH{}'`).
        The values must contain three dots and two `{}` which are
        substituted by station code and component.
    :param str id_default: Default SEED id template.
        The value must contain three dots and two `{}` which are
        substituted by station code and component.
    :param dict ph2comp: mapping of phases to components
        (default: {'P': 'Z', 'S': 'N'})
    :param str encoding: encoding used (default: utf-8)

    :rtype: :class:`~obspy.core.event.Catalog`
    :return: An ObsPy Catalog object.
    """
    if eventid_map is not None:
        eventid_map = {v: k for k, v in eventid_map.items()}
    seed_map = _seed_id_map(inventory, id_map)
    with io.open(filename, 'r', encoding=encoding) as f:
        text = f.read()
    events = [_block2event(block, seed_map, id_default, ph2comp, eventid_map)
              for block in text.split('#')[1:]]
    return Catalog(events)


PHA1 = ('#  {o.time.year}    {o.time.month}   {o.time.day}    {o.time.hour}   '
        '{o.time.minute}   {o.time.second}.{o.time.microsecond:06d}   '
        '{o.latitude}   {o.longitude}   {depth}   {mag}  {he}   {ve}   {rms}'
        '       {evid}\n')
PHA2 = '{p.waveform_id.station_code}  {relt:.4f}  {weight}  {p.phase_hint}\n'


def _map_eventid(evid, eventid_map, used_ids, counter):
    idpha = evid
    if evid in eventid_map:
        idpha = eventid_map[evid]
        if not idpha.isdigit() or len(idpha) > 9:
            msg = ('Invalid value in eventid_map, pha event id has to be '
                   'digit with max 9 digits')
            raise ValueError(msg)
        return idpha
    if not idpha.isdigit():
        idpha = ''.join(char for char in idpha if char.isdigit())
    if len(idpha) > 9:
        idpha = idpha[:9]
    while idpha == '' or idpha in used_ids:
        idpha = str(counter[0])
        counter[0] += 1
    if idpha != evid:
        eventid_map[evid] = idpha
    used_ids.add(idpha)
    return idpha, eventid_map


def _write_pha(catalog, filename, eventid_map=None,
               **kwargs):  # @UnusedVariable
    """
    Write a HypoDD PHA file.

    .. warning::
        This function should NOT be called directly, it registers via the
        the :meth:`~obspy.core.event.Catalog.write` method of an
        ObsPy :class:`~obspy.core.event.Catalog` object, call this instead.

    :type catalog: :class:`~obspy.core.event.catalog.Catalog`
    :param catalog: The ObsPy Catalog object to write.
    :type filename: str or file
    :param filename: Filename to write or open file-like object.
    """
    lines = []
    if eventid_map is None:
        eventid_map = {}
    args_map_eventid = (eventid_map, set(eventid_map.values()), [1000])
    for event in catalog:
        try:
            ori = event.preferred_origin() or event.origins[0]
        except IndexError:
            warn('Skip writing events with missing origin')
            continue
        try:
            mag = event.preferred_magnitude() or event.magnitudes[0]
        except IndexError:
            warn('Missing magnitude will be set to 0.0')
            mag = 0.
        else:
            mag = mag.mag
        evid = event.resource_id.id
        evid = evid.split('/')[-1] if '/' in evid else evid
        evid, eventid_map = _map_eventid(evid, *args_map_eventid)
        rms = ori.quality.standard_error
        rms = rms if rms is not None else 0.0
        he1 = ori.latitude_errors.uncertainty
        he2 = ori.longitude_errors.uncertainty
        shortening = cos(deg2rad(ori.latitude))
        he = max(0. if he1 is None else he1 * DEG2KM,
                 0. if he2 is None else he2 * DEG2KM * shortening)
        ve = ori.depth_errors.uncertainty
        ve = 0. if ve is None else ve / 1000
        line = PHA1.format(o=ori, depth=ori.depth / 1000, mag=mag,
                           he=he, ve=ve, rms=rms,
                           evid=evid)
        lines.append(line)
        weights = {}
        for arrival in ori.arrivals:
            weights[str(arrival.pick_id)] = arrival.time_weight
        for pick in event.picks:
            weight = weights.get(str(pick.resource_id), 1.)
            line = PHA2.format(p=pick, relt=pick.time - ori.time,
                               weight=weight)
            lines.append(line)
    data = ''.join(lines)
    try:
        with open(filename, 'w') as fh:
            fh.write(data)
    except TypeError:
        filename.write(data)
    return None if len(eventid_map) == 0 else eventid_map


if __name__ == '__main__':
    import doctest
    doctest.testmod(exclude_empty=True)
