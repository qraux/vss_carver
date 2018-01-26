#!/usr/bin/env python
# coding=utf-8

#
# vss_carver.py
# Carves and recreates VSS catalog and store from Windows disk image.
#
# Copyright (c) 2018 Minoru Kobayashi <unknownbit@gmail.com> (@unkn0wnbit)
#
# This software is released under the MIT License.
# https://opensource.org/licenses/MIT
#

import argparse
import struct
import binascii
import uuid
import copy
import datetime
from ctypes import *
from calendar import timegm

vss_identifier = b'\x6B\x87\x08\x38\x76\xC1\x48\x4E\xB7\xAE\x04\x04\x6E\x6C\xC7\x52'

class VolumeHeader(LittleEndianStructure):
    _fields_ = (
        ('vssid', c_char * 16),
        ('version', c_uint32),
        ('record_type', c_uint32),
        ('current_offset', c_uint64),
        ('unknown1', c_uint64),
        ('unknown2', c_uint64),
        ('catalog_offset', c_uint64),
        ('maximum_size', c_uint64),
        ('volume_identifier', c_char * 16),
        ('shadow_copy_storage_volume_identifier', c_char * 16),
        ('unknown3', c_uint32),
        ('unknown_empty', c_char * 412)
    )

    def __init__(self):
        self.vssid = vss_identifier
        self.record_type = 0x1
        self.current_offset = 0x1e00
        self.unknown1 = 0x1e00
        self.unknown1 = 0x0
        self.unknown_empty = b'\x00'


class CatalogBlockHeader(LittleEndianStructure):
    _fields_ = (
        ('vssid', c_char * 16),
        ('version', c_uint32),
        ('record_type', c_uint32),
        ('relative_catalog_offset', c_uint64),
        ('current_catalog_offset', c_uint64),
        ('next_catalog_offset', c_uint64),
        ('unknown_empty', c_char * 80)
    )

    def __init__(self, relative=0, current=0, next_offset=0):
        self.vssid = vss_identifier
        self.version = 0x1
        self.record_type = 0x2
        self.relative_catalog_offset = relative
        self.current_catalog_offset = current
        self.next_catalog_offset = next_offset
        self.unknown_empty = b'\x00'


class CatalogEntry0x00(LittleEndianStructure):
    _fields_ = (
        ('catalog_entry_type', c_uint64),
        ('unknown', c_char * 120)
    )

    def __init__(self):
        self.catalog_entry_type = 0x0
        self.unknown = b'\x00'


class CatalogEntry0x01(LittleEndianStructure):
    _fields_ = (
        ('catalog_entry_type', c_uint64),
        ('unknown', c_char * 120)
    )

    def __init__(self):
        self.catalog_entry_type = 0x01
        self.unknown = b'\x00'


class CatalogEntry0x02(LittleEndianStructure):
    _fields_ = (
        ('catalog_entry_type', c_uint64),
        ('volume_size', c_uint64),
        ('store_guid', c_char * 16),
        ('sequence_number', c_uint64),
        ('unknown_flags', c_uint64),
        ('shadow_copy_creation_time', c_uint64),
        ('unknown_empty', c_char * 72)
    )

    def __init__(self):
        self.catalog_entry_type = 0x02
        self.unknown_flags = 0x40
        self.unknown_empty = b'\x00'


class CatalogEntry0x03(LittleEndianStructure):
    _fields_ = (
        ('catalog_entry_type', c_uint64),
        ('store_block_list_offset', c_uint64),
        ('store_guid', c_char * 16),
        ('store_header_offset', c_uint64),
        ('store_block_range_offset', c_uint64),
        ('store_current_bitmap_offset', c_uint64),
        ('ntfs_file_reference', c_uint64),
        ('allocated_size', c_uint64),
        ('store_previous_bitmap_offset', c_uint64),
        ('unknown', c_uint64),
        ('unknown_empty', c_char * 40)
    )

    def __init__(self):
        self.catalog_entry_type = 0x03
        self.ntfs_file_reference = 0x0
        self.allocated_size = 0x0
        self.store_previous_bitmap_offset = 0x0
        self.unknown = 0x0
        self.unknown_empty = b'\x00'


class StoreBlockHeader(LittleEndianStructure):
    _fields_ = (
        ('vssid', c_char * 16),
        ('version', c_uint32),
        ('record_type', c_uint32),
        ('relative_block_offset', c_uint64),
        ('current_block_offset', c_uint64),
        ('next_block_offset', c_uint64),
        ('size_info', c_uint64),
        ('unknown', c_char * 72)
    )

    def __init__(self):
        self.vssid = b'\x00'
        self.version = 0x0
        self.record_type = 0x0
        self.relative_block_offset = 0x0
        self.current_block_offset = 0x0
        self.next_block_offset = 0x0
        self.size_info = 0x0
        self.unknown = b'\x00'
        self.flag_dummy = False


class StoreBlockHeader0x4000(LittleEndianStructure):
    _fields_ = (
        ('vssid', c_char * 16),
        ('version', c_uint32),
        ('record_type', c_uint32),
        ('relative_block_offset', c_uint64),
        ('current_block_offset', c_uint64),
        ('next_block_offset', c_uint64),
        ('size_info', c_uint64),
        ('unknown', c_char * 72),
        ('data', c_char * (0x4000 - 128))
    )

    def __init__(self):
        self.unknown = b'\x00'
        self.data = b'\x00'


class StoreBlockChunk(object):
    def __init__(self, store_block):
        # type: (StoreBlockHeader) -> None
        self.head = copy.deepcopy(store_block)
        self.list_next_block_offset = []
        self.list_next_block_offset.append(store_block.next_block_offset)


def check_vss_enable(disk_image, image_offset):
    volume_header = VolumeHeader()

    disk_image.seek(image_offset + 0xb)
    sector_size = struct.unpack("<H", disk_image.read(2))[0]
    disk_image.seek(image_offset + 0x28)
    number_of_sector = struct.unpack("<Q", disk_image.read(8))[0]
    volume_size = sector_size * number_of_sector + 0x200
    print("Volume size: {0}".format(hex(volume_size)))

    disk_image.seek(image_offset + 0x1e00)
    disk_image.readinto(volume_header)
    if volume_header.vssid == vss_identifier:
        print("Found VSS volume header.")
        print("{0}: {1}".format(hex(0x1e00), binascii.b2a_hex(volume_header.vssid)))
        print("Catalog offset: {0}".format(hex(volume_header.catalog_offset)))
        return volume_header.catalog_offset, volume_size
    else:
        exit("Not found VSS volume header.")


def read_catalog_from_disk_image(disk_image, volume_offset, catalog_offset):
    catalog_block_header = CatalogBlockHeader()
    catalog0x02 = CatalogEntry0x02()
    catalog0x03 = CatalogEntry0x03()
    list_disk_catalog_entry = []
    dict_disk_catalog_entry = {}
    index_disk_catalog_entry = 0

    while True:
        catalog_block_offset = 0
        disk_image.seek(volume_offset + catalog_offset)
        disk_image.readinto(catalog_block_header)
        catalog_block_offset = catalog_block_offset + 128

        while catalog_block_offset < 0x4000 - 128:
            catalog_entry_type = struct.unpack("<Q", disk_image.read(8))[0]
            disk_image.seek(-8, 1)

            if catalog_entry_type == 0x2:
                disk_image.readinto(catalog0x02)
                # if dict_disk_catalog_entry.has_key(catalog0x02.store_guid):
                if catalog0x02.store_guid in dict_disk_catalog_entry:
                    dict_disk_catalog_entry[catalog0x02.store_guid][0] = copy.deepcopy(catalog0x02)
                    list_disk_catalog_entry[index_disk_catalog_entry][0] = copy.deepcopy(catalog0x02)
                else:
                    dict_disk_catalog_entry[catalog0x02.store_guid] = copy.deepcopy(['', ''])
                    dict_disk_catalog_entry[catalog0x02.store_guid][0] = copy.deepcopy(catalog0x02)
                    list_disk_catalog_entry.append(copy.deepcopy(['', '']))
                    list_disk_catalog_entry[index_disk_catalog_entry][0] = copy.deepcopy(catalog0x02)
            elif catalog_entry_type == 0x3:
                disk_image.readinto(catalog0x03)
                # if dict_disk_catalog_entry.has_key(catalog0x03.store_guid):
                if catalog0x03.store_guid in dict_disk_catalog_entry:
                    dict_disk_catalog_entry[catalog0x03.store_guid][1] = copy.deepcopy(catalog0x03)
                    list_disk_catalog_entry[index_disk_catalog_entry][1] = copy.deepcopy(catalog0x03)
                    index_disk_catalog_entry = index_disk_catalog_entry + 1
                else:
                    dict_disk_catalog_entry[catalog0x03.store_guid] = copy.deepcopy(['', ''])
                    dict_disk_catalog_entry[catalog0x03.store_guid][1] = copy.deepcopy(catalog0x03)
                    list_disk_catalog_entry.append(copy.deepcopy(['', '']))
                    list_disk_catalog_entry[index_disk_catalog_entry][0] = copy.deepcopy(catalog0x03)
            else:
                disk_image.seek(128, 1)

            catalog_block_offset = catalog_block_offset + 128

        catalog_offset = catalog_block_header.next_catalog_offset
        if catalog_offset == 0x0:
            break

    return dict_disk_catalog_entry, list_disk_catalog_entry


def carve_data_block(disk_image, image_offset, debug):
    chunk_head = 0
    chunk_head_record_type = 0
    chunk_continue = 0
    dict_store_block = {}
    list_store_block_chunk = []
    index_store_block_chunk = 0
    store_block_header = StoreBlockHeader()

    if debug:
        print("Searching store block chunks.")
    while disk_image.readinto(store_block_header):
        if store_block_header.vssid == vss_identifier and store_block_header.version == 1:
            if store_block_header.record_type in [2, 3, 4, 5, 6]:
                dict_store_block[store_block_header.current_block_offset] = copy.deepcopy(store_block_header)

            if chunk_head == 0:
                chunk_head = store_block_header.current_block_offset
                chunk_head_record_type = store_block_header.record_type
                list_store_block_chunk.append(StoreBlockChunk(store_block_header))
                index_store_block_chunk = index_store_block_chunk + 1

            if chunk_head_record_type == store_block_header.record_type:
                if store_block_header.next_block_offset - store_block_header.current_block_offset > 0x4000 or store_block_header.next_block_offset - store_block_header.current_block_offset < 0x0:
                    if debug:
                        print("{0}-{1}({2}) : Ver:{3} RType:{4} Next:{5}".format(hex(chunk_head), hex(store_block_header.current_block_offset), hex(store_block_header.current_block_offset-chunk_head+0x4000), store_block_header.version, store_block_header.record_type, hex(store_block_header.next_block_offset)))
                    chunk_head = 0
                    chunk_head_record_type = 0
                    chunk_continue = 1

                elif store_block_header.next_block_offset == 0:
                    if debug:
                        print("{0}-{1}({2}) : Ver:{3} RType:{4} Next:{5}".format(hex(chunk_head), hex(store_block_header.current_block_offset), hex(store_block_header.current_block_offset-chunk_head+0x4000), store_block_header.version, store_block_header.record_type, hex(store_block_header.next_block_offset)))
                    chunk_head = 0
                    chunk_head_record_type = 0
                    chunk_continue = 0

                else:
                    chunk_continue = 1

            else:
                if debug:
                    print("{0}-{1}({2}) : Ver:{3} RType:{4}/{5} Next:{6}  Corrupt Chunk?".format(hex(chunk_head), hex(store_block_header.current_block_offset), hex(store_block_header.current_block_offset - chunk_head + 0x4000), store_block_header.version, chunk_head_record_type, store_block_header.record_type, hex(store_block_header.next_block_offset)))
                chunk_head = 0
                chunk_head_record_type = 0
                chunk_continue = 0

        else:
            if chunk_continue == 0:
                chunk_head = 0
                chunk_head_record_type = 0

        image_offset = image_offset + 0x4000
        disk_image.seek(image_offset)

    return dict_store_block, list_store_block_chunk


def group_store_block(list_store_block_chunk, debug):
    snapshot_store_order = (4, 3, 5, 6, 6)
    index_snapshot_store = 0
    flag_get_snapshot = False
    dict_snapshot = {'header': '', 'block': '', 'range': '', 'cur_bitmap': '', 'prev_bitmap': ''}
    list_snapshot_set = []

    for chunk in list_store_block_chunk:
        if chunk.head.record_type == snapshot_store_order[index_snapshot_store]:
            if chunk.head.record_type == 4:
                dict_snapshot['header'] = chunk
                index_snapshot_store = index_snapshot_store + 1

            elif chunk.head.record_type == 3:
                dict_snapshot['block'] = chunk
                index_snapshot_store = index_snapshot_store + 1

            elif chunk.head.record_type == 5:
                dict_snapshot['range'] = chunk
                index_snapshot_store = index_snapshot_store + 1

            elif chunk.head.record_type == 6 and index_snapshot_store == 3:
                dict_snapshot['cur_bitmap'] = chunk
                dict_snapshot['prev_bitmap'] = StoreBlockChunk(StoreBlockHeader())
                index_snapshot_store = index_snapshot_store + 1
                flag_get_snapshot = True

            elif chunk.head.record_type == 6 and index_snapshot_store == 4:
                dict_snapshot['prev_bitmap'] = chunk
                list_snapshot_set.append(copy.deepcopy(dict_snapshot))
                index_snapshot_store = 0
                # flag_get_snapshot = True
                flag_get_snapshot = False

        elif chunk.head.record_type == 4 and index_snapshot_store == 4:
            dict_snapshot['prev_bitmap'] = StoreBlockChunk(StoreBlockHeader())
            list_snapshot_set.append(copy.deepcopy(dict_snapshot))
            dict_snapshot['header'] = chunk
            index_snapshot_store = 1
            # flag_get_snapshot = True
            flag_get_snapshot = False

        else:
            if flag_get_snapshot:
                list_snapshot_set.append(copy.deepcopy(dict_snapshot))
            index_snapshot_store = 0
            flag_get_snapshot = False

    if flag_get_snapshot:
        list_snapshot_set.append(copy.deepcopy(dict_snapshot))

    if debug:
        print("dump list_snapshot_set")
        for store in list_snapshot_set:
            print("header: {0}: RType:{1} Offset:{2}".format(hex(store['header'].head.current_block_offset), store['header'].head.record_type, store['header'].list_next_block_offset))
            print("block : {0}: RType:{1} Offset:{2}".format(hex(store['block'].head.current_block_offset), store['block'].head.record_type, store['block'].list_next_block_offset))
            print("range : {0}: RType:{1} Offset:{2}".format(hex(store['range'].head.current_block_offset), store['range'].head.record_type, store['range'].list_next_block_offset))
            print("curr  : {0}: RType:{1} Offset:{2}".format(hex(store['cur_bitmap'].head.current_block_offset), store['cur_bitmap'].head.record_type, store['cur_bitmap'].list_next_block_offset))
            print("prev  : {0}: RType:{1} Offset:{2}\n".format(hex(store['prev_bitmap'].head.current_block_offset), store['prev_bitmap'].head.record_type, store['prev_bitmap'].list_next_block_offset))

    return list_snapshot_set


def make_list_next_block_offset(dict_store_block, list_next_block_offset, next_block_offset):
    if next_block_offset in dict_store_block:
        if dict_store_block[next_block_offset].next_block_offset in dict_store_block:
            list_next_block_offset.append(dict_store_block[next_block_offset].next_block_offset)
        else:
            list_next_block_offset.append(0x0)
            return False

        if dict_store_block[next_block_offset].next_block_offset == 0x0:
            return True
        else:
            result = make_list_next_block_offset(dict_store_block, list_next_block_offset, dict_store_block[next_block_offset].next_block_offset)
            if result:
                return True
            else:
                return False

    else:
        # list_next_block_offset.append( 0xFFFFFFFFFFFFFFFF )
        # return False, list_next_block_offset

        # Create dummy store block
        for expansion in range(0x4000, 0x100000, 0x4000):
            # if dict_store_block.has_key(next_block_offset + expansion) and dict_store_block[next_block_offset + expansion].record_type == 3:
            if (next_block_offset + expansion) in dict_store_block and dict_store_block[next_block_offset + expansion].record_type == 3:
                for count in range(expansion//0x4000):
                    offset = count * 0x4000
                    dict_store_block[next_block_offset + offset] = copy.deepcopy(StoreBlockHeader())
                    dict_store_block[next_block_offset + offset].vssid = vss_identifier
                    dict_store_block[next_block_offset + offset].version = 0x1
                    dict_store_block[next_block_offset + offset].record_type = 0x3
                    dict_store_block[next_block_offset + offset].next_block_offset = next_block_offset + ((count + 1) * 0x4000)
                    dict_store_block[next_block_offset + offset].size_info = 0x0
                    dict_store_block[next_block_offset + offset].flag_dummy = True

                    list_next_block_offset.append(next_block_offset)
                return True

        list_next_block_offset.append(0x0)
        return False


def check_store_block_next_block_offset(dict_store_block, list_snapshot_set, debug):
    for store in list_snapshot_set:
        for record_type in store.keys():
            chunk = store[record_type]
            if chunk.head.next_block_offset != 0x0:
                result = make_list_next_block_offset(dict_store_block, chunk.list_next_block_offset, chunk.head.next_block_offset)

            if len(chunk.list_next_block_offset) >= 2 and dict_store_block[chunk.list_next_block_offset[-2]].next_block_offset != 0x0:
                dict_store_block[chunk.list_next_block_offset[-2]].next_block_offset = 0x0

    if debug:
        print("dump list_snapshot_set")
        for store in list_snapshot_set:
            print("header: {0}: RType:{1} Offset:{2}".format(hex(store['header'].head.current_block_offset), store['header'].head.record_type, store['header'].list_next_block_offset))
            print("block : {0}: RType:{1} Offset:{2}".format(hex(store['block'].head.current_block_offset), store['block'].head.record_type, store['block'].list_next_block_offset))
            print("range : {0}: RType:{1} Offset:{2}".format(hex(store['range'].head.current_block_offset), store['range'].head.record_type, store['range'].list_next_block_offset))
            print("curr  : {0}: RType:{1} Offset:{2}".format(hex(store['cur_bitmap'].head.current_block_offset), store['cur_bitmap'].head.record_type, store['cur_bitmap'].list_next_block_offset))
            print("prev  : {0}: RType:{1} Offset:{2}\n".format(hex(store['prev_bitmap'].head.current_block_offset), store['prev_bitmap'].head.record_type, store['prev_bitmap'].list_next_block_offset))

    return list_snapshot_set


def deduplicate_catalog(dict_disk_catalog_entry, list_snapshot_set):
    list_remove = []

    for snapshot_set in list_snapshot_set:
        for store_guid in dict_disk_catalog_entry.keys():
            if dict_disk_catalog_entry[store_guid][1].store_header_offset == snapshot_set['header'].head.current_block_offset:
                list_remove.append(snapshot_set)

    for index in list_remove:
        list_snapshot_set.remove(index)


def write_store(store_file, list_disk_catalog_entry, dict_store_block, list_snapshot_set, disk_image, image_offset):
    index_store_file = 0
    index_disk_catalog_entry = 0

    store_file_offset = 0
    store_block = StoreBlockHeader0x4000()
    catalog0x03 = []

    f_store = open(store_file, "wb")

    #
    # Catalogs from Disk Image
    for disk_catalog_entry in list_disk_catalog_entry:
        #
        # Store Header
        disk_image.seek(disk_catalog_entry[1].store_header_offset + image_offset)
        disk_image.readinto(store_block)
        store_block.relative_block_offset = store_file_offset
        store_block.current_block_offset = store_file_offset
        next_block_offset = store_block.next_block_offset
        if next_block_offset != 0x0:
            store_block.next_block_offset = store_file_offset + 0x4000
            list_disk_catalog_entry[index_disk_catalog_entry][1].next_block_offset = store_file_offset + 0x4000

        list_disk_catalog_entry[index_disk_catalog_entry][1].store_header_offset = store_file_offset

        f_store.write(store_block)
        store_file_offset = store_file_offset + 0x4000

        while next_block_offset > 0x0:
            disk_image.seek(next_block_offset + image_offset)
            disk_image.readinto(store_block)
            store_block.relative_block_offset = store_file_offset
            store_block.current_block_offset = store_file_offset
            next_block_offset = store_block.next_block_offset
            if next_block_offset != 0x0:
                store_block.next_block_offset = store_file_offset + 0x4000
                list_disk_catalog_entry[index_disk_catalog_entry][1].next_block_offset = store_file_offset + 0x4000
            f_store.write(store_block)
            store_file_offset = store_file_offset + 0x4000

        #
        # Store Block List
        disk_image.seek(disk_catalog_entry[1].store_block_list_offset + image_offset)
        disk_image.readinto(store_block)
        store_block.relative_block_offset = store_file_offset
        store_block.current_block_offset = store_file_offset
        next_block_offset = store_block.next_block_offset
        if next_block_offset != 0x0:
            store_block.next_block_offset = store_file_offset + 0x4000
            # list_disk_catalog_entry[index_disk_catalog_entry][1].next_block_offset = store_file_offset + 0x4000

        list_disk_catalog_entry[index_disk_catalog_entry][1].store_block_list_offset = store_file_offset

        f_store.write(store_block)
        store_file_offset = store_file_offset + 0x4000

        while next_block_offset > 0x0:
            disk_image.seek(next_block_offset + image_offset)
            disk_image.readinto(store_block)
            store_block.relative_block_offset = store_file_offset
            store_block.current_block_offset = store_file_offset
            next_block_offset = store_block.next_block_offset
            if next_block_offset != 0x0:
                store_block.next_block_offset = store_file_offset + 0x4000
                # list_disk_catalog_entry[index_disk_catalog_entry][1].next_block_offset = store_file_offset + 0x4000
            f_store.write(store_block)
            store_file_offset = store_file_offset + 0x4000

        #
        # Store Block Range
        disk_image.seek(disk_catalog_entry[1].store_block_range_offset + image_offset)
        disk_image.readinto(store_block)
        store_block.relative_block_offset = store_file_offset
        store_block.current_block_offset = store_file_offset
        next_block_offset = store_block.next_block_offset
        if next_block_offset != 0x0:
            store_block.next_block_offset = store_file_offset + 0x4000
            list_disk_catalog_entry[index_disk_catalog_entry][1].next_block_offset = store_file_offset + 0x4000

        list_disk_catalog_entry[index_disk_catalog_entry][1].store_block_range_offset = store_file_offset

        f_store.write(store_block)
        store_file_offset = store_file_offset + 0x4000

        while next_block_offset > 0x0:
            disk_image.seek(next_block_offset + image_offset)
            disk_image.readinto(store_block)
            store_block.relative_block_offset = store_file_offset
            store_block.current_block_offset = store_file_offset
            next_block_offset = store_block.next_block_offset
            if next_block_offset != 0x0:
                store_block.next_block_offset = store_file_offset + 0x4000
                list_disk_catalog_entry[index_disk_catalog_entry][1].next_block_offset = store_file_offset + 0x4000
            f_store.write(store_block)
            store_file_offset = store_file_offset + 0x4000

        #
        # Store Current Bitmap
        disk_image.seek(disk_catalog_entry[1].store_current_bitmap_offset + image_offset)
        disk_image.readinto(store_block)
        store_block.relative_block_offset = store_file_offset
        store_block.current_block_offset = store_file_offset
        next_block_offset = store_block.next_block_offset
        if next_block_offset != 0x0:
            store_block.next_block_offset = store_file_offset + 0x4000
            list_disk_catalog_entry[index_disk_catalog_entry][1].next_block_offset = store_file_offset + 0x4000

        list_disk_catalog_entry[index_disk_catalog_entry][1].store_current_bitmap_offset = store_file_offset

        f_store.write(store_block)
        store_file_offset = store_file_offset + 0x4000

        while next_block_offset > 0x0:
            disk_image.seek(next_block_offset + image_offset)
            disk_image.readinto(store_block)
            store_block.relative_block_offset = store_file_offset
            store_block.current_block_offset = store_file_offset
            next_block_offset = store_block.next_block_offset
            if next_block_offset != 0x0:
                store_block.next_block_offset = store_file_offset + 0x4000
                list_disk_catalog_entry[index_disk_catalog_entry][1].next_block_offset = store_file_offset + 0x4000
            f_store.write(store_block)
            store_file_offset = store_file_offset + 0x4000

        #
        # Store Previous Bitmap
        if disk_catalog_entry[1].store_previous_bitmap_offset != 0x0:  # この if 文をカービングしたストアにも入れる
            disk_image.seek(disk_catalog_entry[1].store_previous_bitmap_offset + image_offset)
            disk_image.readinto(store_block)
            store_block.relative_block_offset = store_file_offset
            store_block.current_block_offset = store_file_offset
            next_block_offset = store_block.next_block_offset
            if next_block_offset != 0x0:
                store_block.next_block_offset = store_file_offset + 0x4000
                list_disk_catalog_entry[index_disk_catalog_entry][1].next_block_offset = store_file_offset + 0x4000

            list_disk_catalog_entry[index_disk_catalog_entry][1].store_previous_bitmap_offset = store_file_offset

            f_store.write(store_block)
            store_file_offset = store_file_offset + 0x4000

            while next_block_offset > 0x0:
                disk_image.seek(next_block_offset + image_offset)
                disk_image.readinto(store_block)
                store_block.relative_block_offset = store_file_offset
                store_block.current_block_offset = store_file_offset
                next_block_offset = store_block.next_block_offset
                if next_block_offset != 0x0:
                    store_block.next_block_offset = store_file_offset + 0x4000
                    list_disk_catalog_entry[index_disk_catalog_entry][1].next_block_offset = store_file_offset + 0x4000
                f_store.write(store_block)
                store_file_offset = store_file_offset + 0x4000

        index_disk_catalog_entry = index_disk_catalog_entry + 1

    #
    # Carved Catalogs
    for snapshot_set in list_snapshot_set:
        catalog0x03.append(copy.deepcopy(CatalogEntry0x03()))

        #
        # Store Header
        disk_image.seek(snapshot_set['header'].head.current_block_offset + image_offset)
        disk_image.readinto(store_block)
        store_block.relative_block_offset = store_file_offset
        store_block.current_block_offset = store_file_offset
        if snapshot_set['header'].head.next_block_offset != 0x0:
            store_block.next_block_offset = store_file_offset + 0x4000

        catalog0x03[index_store_file].store_header_offset = store_file_offset

        f_store.write(store_block)
        store_file_offset = store_file_offset + 0x4000

        for next_block_offset in snapshot_set['header'].list_next_block_offset:
            if next_block_offset == 0x0:
                break
            disk_image.seek(next_block_offset + image_offset)
            disk_image.readinto(store_block)
            store_block.relative_block_offset = store_file_offset
            store_block.current_block_offset = store_file_offset
            if dict_store_block[next_block_offset].next_block_offset != 0 and store_block.next_block_offset != 0x0:
                store_block.next_block_offset = store_file_offset + 0x4000
            f_store.write(store_block)
            store_file_offset = store_file_offset + 0x4000

        #
        # Store Block List
        disk_image.seek(snapshot_set['block'].head.current_block_offset + image_offset)
        disk_image.readinto(store_block)
        store_block.relative_block_offset = store_file_offset
        store_block.current_block_offset = store_file_offset
        if snapshot_set['block'].head.next_block_offset != 0x0:
            store_block.next_block_offset = store_file_offset + 0x4000

        catalog0x03[index_store_file].store_block_list_offset = store_file_offset

        f_store.write(store_block)
        store_file_offset = store_file_offset + 0x4000

        if snapshot_set['block'].head.next_block_offset != 0x0:
            for next_block_offset in snapshot_set['block'].list_next_block_offset:
                if next_block_offset == 0x0:
                    break
                else:
                    if not dict_store_block[next_block_offset].flag_dummy:
                        disk_image.seek(next_block_offset + image_offset)
                        disk_image.readinto(store_block)
                    else:
                        original_data_block_offset = b'\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF'
                        relative_store_data_block_offset = b'\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF'
                        store_data_block_offset = b'\xFF\xFF\xFF\xFF\xFF\xFF\xFF\xFF'
                        flags = b'\x00\x00\x00\x00'
                        allocation_bitmap = b'\x00\x00\x00\x00'
                        store_block.data = (original_data_block_offset + relative_store_data_block_offset + store_data_block_offset + flags + allocation_bitmap) * ((0x4000-128)//32)

                    store_block.relative_block_offset = store_file_offset
                    store_block.current_block_offset = store_file_offset
                    if dict_store_block[next_block_offset].next_block_offset != 0 and store_block.next_block_offset != 0x0:
                        store_block.next_block_offset = store_file_offset + 0x4000
                    f_store.write(store_block)
                    store_file_offset = store_file_offset + 0x4000
        # f_store.write( store_block )
        # store_file_offset = store_file_offset + 0x4000

        #
        # Store Range
        disk_image.seek(snapshot_set['range'].head.current_block_offset + image_offset)
        disk_image.readinto(store_block)
        store_block.relative_block_offset = store_file_offset
        store_block.current_block_offset = store_file_offset
        if snapshot_set['range'].head.next_block_offset != 0x0:
            store_block.next_block_offset = store_file_offset + 0x4000

        catalog0x03[index_store_file].store_block_range_offset = store_file_offset

        f_store.write(store_block)
        store_file_offset = store_file_offset + 0x4000

        for next_block_offset in snapshot_set['range'].list_next_block_offset:
            if next_block_offset == 0x0:
                break
            disk_image.seek(next_block_offset + image_offset)
            disk_image.readinto(store_block)
            store_block.relative_block_offset = store_file_offset
            store_block.current_block_offset = store_file_offset
            if dict_store_block[next_block_offset].next_block_offset != 0 and store_block.next_block_offset != 0x0:
                store_block.next_block_offset = store_file_offset + 0x4000
            f_store.write(store_block)
            store_file_offset = store_file_offset + 0x4000

        #
        # Store Current Bitmap
        disk_image.seek(snapshot_set['cur_bitmap'].head.current_block_offset + image_offset)
        disk_image.readinto(store_block)
        store_block.relative_block_offset = store_file_offset
        store_block.current_block_offset = store_file_offset
        if snapshot_set['cur_bitmap'].head.next_block_offset != 0x0:
            store_block.next_block_offset = store_file_offset + 0x4000

        catalog0x03[index_store_file].store_current_bitmap_offset = store_file_offset

        f_store.write(store_block)
        store_file_offset = store_file_offset + 0x4000

        for next_block_offset in snapshot_set['cur_bitmap'].list_next_block_offset:
            if next_block_offset == 0x0:
                break
            disk_image.seek(next_block_offset + image_offset)
            disk_image.readinto(store_block)
            store_block.relative_block_offset = store_file_offset
            store_block.current_block_offset = store_file_offset
            if dict_store_block[next_block_offset].next_block_offset != 0 and store_block.next_block_offset != 0x0:
                store_block.next_block_offset = store_file_offset + 0x4000
            f_store.write(store_block)
            store_file_offset = store_file_offset + 0x4000

        #
        # Store Previous Bitmap
        if snapshot_set['prev_bitmap'].head.current_block_offset != 0x0:
            disk_image.seek(snapshot_set['prev_bitmap'].head.current_block_offset + image_offset)
            disk_image.readinto(store_block)
            store_block.relative_block_offset = store_file_offset
            store_block.current_block_offset = store_file_offset
            if snapshot_set['prev_bitmap'].head.next_block_offset != 0x0:
                store_block.next_block_offset = store_file_offset + 0x4000

            catalog0x03[index_store_file].store_previous_bitmap_offset = store_file_offset

            f_store.write(store_block)
            store_file_offset = store_file_offset + 0x4000

            for next_block_offset in snapshot_set['prev_bitmap'].list_next_block_offset:
                if next_block_offset == 0x0:
                    break
                disk_image.seek(next_block_offset + image_offset)
                disk_image.readinto(store_block)
                store_block.relative_block_offset = store_file_offset
                store_block.current_block_offset = store_file_offset
                # 他の箇所も下の行と同様に直す
                if dict_store_block[next_block_offset].next_block_offset != 0 and store_block.next_block_offset != 0x0:
                    store_block.next_block_offset = store_file_offset + 0x4000
                else:
                    store_block.next_block_offset = 0x0
                f_store.write(store_block)
                store_file_offset = store_file_offset + 0x4000

        index_store_file = index_store_file + 1

    f_store.close()
    return catalog0x03


def write_catalog(catalog_file, list_disk_catalog_entry, list_snapshot_set, catalog0x03, volume_size):
    epoch_as_filetime = 116444736000000000  # 1970/1/1 as MS FILETIME
    hundreds_of_nanoseconds = 10000000
    catalog0x02 = CatalogEntry0x02()
    list_catalog_entry = []
    index_list_catalog = 1
    flag_disk_catalog_finish = False
    flag_catalog_finish = False

    if len(list_disk_catalog_entry) > 0:
        sequence_number = list_disk_catalog_entry[-1][0].sequence_number
        creation_time = list_disk_catalog_entry[-1][0].shadow_copy_creation_time
    else:
        sequence_number = len(catalog0x03)
        now = datetime.datetime.now()
        creation_time = epoch_as_filetime + (timegm([now.year, now.month, now.day, now.hour, now.minute, now.second]) * hundreds_of_nanoseconds)

    for snapshot_set in list_snapshot_set:
        guid = uuid.uuid1().bytes

        catalog0x02.volume_size = volume_size
        catalog0x02.store_guid = guid
        catalog0x02.sequence_number = sequence_number - index_list_catalog
        catalog0x02.shadow_copy_creation_time = creation_time - hundreds_of_nanoseconds * 60 * 60 * index_list_catalog

        catalog0x03[-index_list_catalog].store_guid = guid

        list_catalog_entry.append(copy.deepcopy((catalog0x02, catalog0x03[-index_list_catalog])))
        index_list_catalog = index_list_catalog + 1

    print("writing catalog file.")
    index_list_disk_catalog = 0
    # index_list_catalog = len(list_catalog_entry)
    index_list_catalog = 0
    f_catalog = open(catalog_file, "wb")
    for catalog_offset in [0x0, 0x4000, 0x8000, 0xc000]:
        buf = 0x0
        if catalog_offset == 0xc000:
            next_block_offset = 0x0
        else:
            next_block_offset = catalog_offset + 0x4000

        if buf == 0:
            f_catalog.write(CatalogBlockHeader(catalog_offset, catalog_offset, next_block_offset))
            buf = buf + 128

        if not flag_disk_catalog_finish and len(list_disk_catalog_entry) > 0:
            # while next_block_offset - buf > 128 * 2 and index_list_disk_catalog < len(list_disk_catalog_entry):
            while 0x4000 - buf > 128 * 2 and index_list_disk_catalog < len(list_disk_catalog_entry):
                f_catalog.write(list_disk_catalog_entry[index_list_disk_catalog][0])
                f_catalog.write(list_disk_catalog_entry[index_list_disk_catalog][1])
                buf = buf + 128 * 2
                index_list_disk_catalog = index_list_disk_catalog + 1
                if index_list_disk_catalog == len(list_disk_catalog_entry):
                    flag_disk_catalog_finish = True
                    break
        elif len(list_disk_catalog_entry) == 0:
            flag_disk_catalog_finish = True

        if flag_disk_catalog_finish and not flag_catalog_finish and len(list_catalog_entry) > 0:
            # while next_block_offset - buf > 128 * 2 and index_list_catalog < len(list_catalog_entry):
            while 0x4000 - buf > 128 * 2 and index_list_catalog < len(list_catalog_entry):
                f_catalog.write(list_catalog_entry[index_list_catalog][0])
                f_catalog.write(list_catalog_entry[index_list_catalog][1])
                buf = buf + 128 * 2
                index_list_catalog = index_list_catalog + 1
                if index_list_catalog == len(list_catalog_entry):
                    flag_catalog_finish = True
                    break
        elif len(list_catalog_entry) == 0:
            flag_catalog_finish = True

        for i in range((0x4000 - buf) // 128):
            f_catalog.write(CatalogEntry0x00())
            buf = buf + 128

    f_catalog.close()


def main():
    parser = argparse.ArgumentParser(description="Carve and rebuild VSS snapshot catalog and store from disk image.")
    parser.add_argument('-o', '--offset', action='store', type=int,
                        help='offset to start of volume in disk image.')
    parser.add_argument('-i', '--image', action='store', type=str,
                        help='path to disk image.')
    parser.add_argument('-c', '--catalog', type=str,
                        help='path to catalog file.')
    parser.add_argument('-s', '--store', type=str,
                        help='path to store file.')
    parser.add_argument('--debug', action='store_true', default=False,
                        help='debug mode if this flag is set (default: False)')
    args = parser.parse_args()

    if args.image is None or args.catalog is None or args.store is None:
        exit("too few arguments.")

    # win10en : 525336576
    # seccamp-win7 : 105906176

    disk_image = open(args.image, "rb")

    print("="*50)
    print("Stage 1: Check VSS enabled.")
    catalog_offset, volume_size = check_vss_enable(disk_image, args.offset)

    print("=" * 50)
    print("Stage 2: Reading catalog from disk image.")
    if catalog_offset:
        dict_disk_catalog_entry, list_disk_catalog_entry = read_catalog_from_disk_image(disk_image, args.offset, catalog_offset)
    else:
        print("VSS snapshot was enabled. But all snapshots were deleted.")
        dict_disk_catalog_entry = {}
        list_disk_catalog_entry = []

    print("="*50)
    print("Stage 3: Carving data blocks.")
    dict_store_block, list_store_block_chunk = carve_data_block(disk_image, args.offset, args.debug)

    print("="*50)
    print("Stage 4: Grouping store blocks by VSS snapshot.")
    list_snapshot_set = group_store_block(list_store_block_chunk, args.debug)

    print("="*50)
    print("Stage 5: Checking next block offset lists.")
    check_store_block_next_block_offset(dict_store_block, list_snapshot_set, args.debug)

    print("="*50)
    print("Stage 6: Deduplicate carved catalog entries.")
    deduplicate_catalog(dict_disk_catalog_entry, list_snapshot_set)

    print("="*50)
    print("Stage 7: Writing store file.")
    catalog0x03 = write_store(args.store, list_disk_catalog_entry, dict_store_block, list_snapshot_set, disk_image, args.offset)

    print("="*50)
    print("Stage 8: Writing catalog file.")
    write_catalog(args.catalog, list_disk_catalog_entry, list_snapshot_set, catalog0x03, volume_size)

    disk_image.close()


if __name__ == "__main__":
    main()