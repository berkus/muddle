"""
Rules cache - we cache the dependencies so that we don't have to recalculate them all the time
"""
import os
import sys
import hashlib
from modulefinder import ModuleFinder


def hash_file(path):
    """ A function to calculate the hash of the file found at 'path'
    """
    md5 = hashlib.md5()
    chunk_size = 128 * md5.block_size
    with open(path, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            md5.update(chunk)
    return md5.hexdigest()

def find_modules(path):
    """
    Find the imports in the module at 'path' that come from the same directory
    :param path: The path to the python script we are interested in
    :return: A list of files including path and any modules imported that come from the
            same directory
    """
    directory = os.path.dirname(path)

    # Add directory to the python path so we can find the imports
    sys.path.insert(0, directory)

    finder = ModuleFinder()
    finder.run_script(path)

    modules = []
    for name, mod in finder.modules.iteritems():
        module_path = str(mod.__file__)
        if os.path.dirname(module_path) == directory:
            modules.append(module_path)

    return modules


def hash_file_and_imports(path):
    """ Recursively hash this file and imports from within same directory

        We make an effort to deal with imported build descriptions.
        The way we do this is to check the imports and any from within the
        build tree are hashed too.

         :return a single hash that changes when any of the files we care about
         change.
    """
    modules = find_modules(path)

    # Now we just hash each of the module files
    hashes = []
    for module in modules:
        if module == path:
            hashes.append(hash_file(module))
        else:
            # And recurse into imports
            hashes.append(hash_file_and_imports(module))

    # Then concatenate the hashes and hash that
    hash_cat = ''
    for hash in hashes:
        hash_cat += hash
    return hashlib.md5(hash_cat).hexdigest()
