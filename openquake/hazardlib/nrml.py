# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (C) 2014-2017 GEM Foundation
#
# OpenQuake is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OpenQuake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake. If not, see <http://www.gnu.org/licenses/>.

"""
From Node objects to NRML files and viceversa
------------------------------------------------------

It is possible to save a Node object into a NRML file by using the
function ``write(nodes, output)`` where output is a file
object. If you want to make sure that the generated file is valid
according to the NRML schema just open it in 'w+' mode: immediately
after writing it will be read and validated. It is also possible to
convert a NRML file into a Node object with the routine
``read(node, input)`` where input is the path name of the
NRML file or a file object opened for reading. The file will be
validated as soon as opened.

For instance an exposure file like the following::

  <?xml version='1.0' encoding='utf-8'?>
  <nrml xmlns="http://openquake.org/xmlns/nrml/0.4"
        xmlns:gml="http://www.opengis.net/gml">
    <exposureModel
        id="my_exposure_model_for_population"
        category="population"
        taxonomySource="fake population datasource">

      <description>
        Sample population
      </description>

      <assets>
        <asset id="asset_01" number="7" taxonomy="IT-PV">
            <location lon="9.15000" lat="45.16667" />
        </asset>

        <asset id="asset_02" number="7" taxonomy="IT-CE">
            <location lon="9.15333" lat="45.12200" />
        </asset>
      </assets>
    </exposureModel>
  </nrml>

can be converted as follows:

>> nrml = read(<path_to_the_exposure_file.xml>)

Then subnodes and attributes can be conveniently accessed:

>> nrml.exposureModel.assets[0]['taxonomy']
'IT-PV'
>> nrml.exposureModel.assets[0]['id']
'asset_01'
>> nrml.exposureModel.assets[0].location['lon']
'9.15000'
>> nrml.exposureModel.assets[0].location['lat']
'45.16667'

The Node class provides no facility to cast strings into Python types;
this is a job for the Node class which can be subclassed and
supplemented by a dictionary of validators.
"""
from __future__ import print_function
import re
import sys
import decimal
import logging
import operator
import numpy

from openquake.baselib.general import CallableDict, groupby
from openquake.baselib.node import (
    node_to_xml, context, Node, striptag, ValidatingXmlParser, floatformat)
from openquake.hazardlib import valid, sourceconverter

F64 = numpy.float64
NAMESPACE = 'http://openquake.org/xmlns/nrml/0.4'
NRML05 = 'http://openquake.org/xmlns/nrml/0.5'
GML_NAMESPACE = 'http://www.opengis.net/gml'
SERIALIZE_NS_MAP = {None: NAMESPACE, 'gml': GML_NAMESPACE}
PARSE_NS_MAP = {'nrml': NAMESPACE, 'gml': GML_NAMESPACE}


class DuplicatedID(Exception):
    """Raised when two sources with the same ID are found in a source model"""


def get_tag_version(nrml_node):
    """
    Extract from a node of kind NRML the tag and the version. For instance
    from '{http://openquake.org/xmlns/nrml/0.4}fragilityModel' one gets
    the pair ('fragilityModel', 'nrml/0.4').
    """
    version, tag = re.search(r'(nrml/[\d\.]+)\}(\w+)', nrml_node.tag).groups()
    return tag, version


def parse(fname, *args):
    """
    Parse a NRML file and return an associated Python object. It works by
    calling nrml.read() and node_to_obj() in sequence.
    """
    [node] = read(fname)
    return node_to_obj(node, fname, *args)

node_to_obj = CallableDict(keyfunc=get_tag_version, keymissing=lambda n, f: n)
# dictionary of functions with at least two arguments, node and fname


@node_to_obj.add(('sourceModel', 'nrml/0.4'))
def get_source_model_04(node, fname, converter):
    sources = []
    source_ids = set()
    converter.fname = fname
    for no, src_node in enumerate(node, 1):
        src = converter.convert_node(src_node)
        if src.source_id in source_ids:
            raise DuplicatedID(
                'The source ID %s is duplicated!' % src.source_id)
        sources.append(src)
        source_ids.add(src.source_id)
        if no % 10000 == 0:  # log every 10,000 sources parsed
            logging.info('Instantiated %d sources from %s', no, fname)
    if no % 10000 != 0:
        logging.info('Instantiated %d sources from %s', no, fname)
    groups = groupby(
        sources, operator.attrgetter('tectonic_region_type'))
    return sorted(sourceconverter.SourceGroup(trt, srcs)
                  for trt, srcs in groups.items())


@node_to_obj.add(('sourceModel', 'nrml/0.5'))
def get_source_model_05(node, fname, converter):
    converter.fname = fname
    groups = []  # expect a sequence of sourceGroup nodes
    for src_group in node:
        with context(fname, src_group):
            if 'sourceGroup' not in src_group.tag:
                raise ValueError('expected sourceGroup')
        groups.append(converter.convert_node(src_group))
    return sorted(groups)

validators = {
    'strike': valid.strike_range,
    'dip': valid.dip_range,
    'rake': valid.rake_range,
    'magnitude': valid.positivefloat,
    'lon': valid.longitude,
    'lat': valid.latitude,
    'depth': valid.positivefloat,
    'upperSeismoDepth': valid.positivefloat,
    'lowerSeismoDepth': valid.positivefloat,
    'posList': valid.posList,
    'pos': valid.lon_lat,
    'aValue': float,
    'bValue': valid.positivefloat,
    'magScaleRel': valid.mag_scale_rel,
    'tectonicRegion': str,
    'ruptAspectRatio': valid.positivefloat,
    'maxMag': valid.positivefloat,
    'minMag': valid.positivefloat,
    'binWidth': valid.positivefloat,
    'probability': valid.probability,
    'occurRates': valid.positivefloats,
    'probs_occur': valid.pmf,
    'weight': valid.probability,
    'uncertaintyWeight': decimal.Decimal,
    'alongStrike': valid.probability,
    'downDip': valid.probability,
    'totalMomentRate': valid.positivefloat,
    'characteristicRate': valid.positivefloat,
    'characteristicMag': valid.positivefloat,
    'magnitudes': valid.positivefloats,
    'id': valid.simple_id,
    'rupture.id': valid.utf8,  # event tag
    'discretization': valid.compose(valid.positivefloat, valid.nonzero),
    'IML': valid.positivefloats,  # used in NRML 0.4
    'imt': valid.intensity_measure_type,
    'imls': valid.positivefloats,
    'poes': valid.positivefloats,
    'description': valid.utf8_not_empty,
    'noDamageLimit': valid.NoneOr(valid.positivefloat),
    'investigationTime': valid.positivefloat,
    'poEs': valid.probabilities,
    'gsimTreePath': lambda v: v.split('_'),
    'sourceModelTreePath': lambda v: v.split('_'),
    'poE': valid.probability,
    'IMLs': valid.positivefloats,
    'pos': valid.lon_lat,
    'IMT': str,
    'saPeriod': valid.positivefloat,
    'saDamping': valid.positivefloat,
    'quantileValue': valid.positivefloat,
    'investigationTime': valid.positivefloat,
    'poE': valid.probability,
    'periods': valid.positivefloats,
    'pos': valid.lon_lat,
    'IMLs': valid.positivefloats,
    'lon': valid.longitude,
    'lat': valid.latitude,
    'magBinEdges': valid.integers,
    'distBinEdges': valid.integers,
    'epsBinEdges': valid.integers,
    'lonBinEdges': valid.longitudes,
    'latBinEdges': valid.latitudes,
    'type': valid.namelist,
    'dims': valid.positiveints,
    'poE': valid.probability,
    'iml': valid.positivefloat,
    'index': valid.positiveints,
    'value': valid.positivefloat,
    'assetLifeExpectancy': valid.positivefloat,
    'interestRate': valid.positivefloat,
    'statistics': valid.Choice('mean', 'quantile'),
    'pos': valid.lon_lat,
    'gmv': valid.positivefloat,
    'spacing': valid.positivefloat,
    'srcs_weights': valid.weights,
}


def read(source, chatty=True, stop=None):
    """
    Convert a NRML file into a validated Node object. Keeps
    the entire tree in memory.

    :param source:
        a file name or file object open for reading
    """
    vparser = ValidatingXmlParser(validators, stop)
    nrml = vparser.parse_file(source)
    assert striptag(nrml.tag) == 'nrml', nrml.tag
    # extract the XML namespace URL ('http://openquake.org/xmlns/nrml/0.5')
    xmlns = nrml.tag.split('}')[0][1:]
    if xmlns != NRML05 and chatty:
        # for the moment NRML04 is still supported, so we hide the warning
        logging.debug('%s is at an outdated version: %s', source, xmlns)
    nrml['xmlns'] = xmlns
    nrml['xmlns:gml'] = GML_NAMESPACE
    return nrml


def write(nodes, output=sys.stdout, fmt='%.7E', gml=True, xmlns=None):
    """
    Convert nodes into a NRML file. output must be a file
    object open in write mode. If you want to perform a
    consistency check, open it in read-write mode, then it will
    be read after creation and validated.

    :params nodes: an iterable over Node objects
    :params output: a file-like object in write or read-write mode
    :param fmt: format used for writing the floats (default '%.7E')
    :param gml: add the http://www.opengis.net/gml namespace
    :param xmlns: NRML namespace like http://openquake.org/xmlns/nrml/0.4
    """
    root = Node('nrml', nodes=nodes)
    namespaces = {xmlns or NRML05: ''}
    if gml:
        namespaces[GML_NAMESPACE] = 'gml:'
    with floatformat(fmt):
        node_to_xml(root, output, namespaces)
    if hasattr(output, 'mode') and '+' in output.mode:  # read-write mode
        output.seek(0)
        read(output)  # validate the written file


if __name__ == '__main__':
    import sys
    for fname in sys.argv[1:]:
        print('****** %s ******' % fname)
        print(read(fname).to_str())
        print()
