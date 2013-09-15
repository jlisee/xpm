# Author: Joseph Lisee <jlisee@gmail.com>

# Python Imports
import copy
import fnmatch
import hashlib
import os
import re
import string
import subprocess
import sys
import tarfile
import urllib
import yaml

from contextlib import contextmanager


def shellcmd(cmd, echo=True, stream=True, shell=True):
    """
    Run 'cmd' in the shell and return its standard out.
    """

    if echo:
        print '[cmd] {0}'.format(cmd)

    if stream and echo:
        out = None

        subprocess.check_call(cmd, stderr=sys.stderr, stdout=sys.stdout,
                              shell=shell)
    else:
        try:
            out = subprocess.check_output(cmd, stderr=sys.stderr, shell=shell)

        except subprocess.CalledProcessError as c:
            # Capture the process output
            out = c.output
            raise c

        finally:
            if echo:
                print out

    return out


def fetch_url(url, local_path):
    """
    Download the remote url into the local path
    """

    print 'Downloading',

    # Determine what the local file will be called
    local_filename = os.path.basename(url)

    def progress(count, block_size, total_size):
        """
        Super simple progress reporter.
        """
        percent = int(count*block_size*100/total_size)

        args = (local_filename, percent, total_size)
        sys.stdout.write("\r%s - %2d%% of %d bytes" % args)
        sys.stdout.flush()

    # Down the file
    filename, headers = urllib.urlretrieve(url, local_path,
                                           reporthook = progress)

    return filename


def hash_file(f, hash_type, block_size=2**20):
    """
    Computes the hash sum for a file
    """

    hash_state = hash_type()

    while True:
        data = f.read(block_size)

        if not data:
            break

        hash_state.update(data)

    return hash_state.hexdigest()


def unpack_tarball(tar_url, extract_path='.'):
    """
    Extracts a tar file to disk, return root directory (and assumes
    there is one).
    """

    print 'Unpacking',tar_url

    # Open and extract
    with tarfile.open(tar_url, 'r') as tar:
        tar.extractall(extract_path)
        filenames = tar.getnames()

    # Get root (the shortest path will be the root if there is one)
    unpack_dir = sorted(filenames)[0]

    return os.path.join(extract_path, unpack_dir)


def make_tarball(output_filename, source_dir):
    """
    Target up the given directory.
    """

    with tarfile.open(output_filename, "w:gz") as tar:
        tar.add(source_dir, arcname=os.path.basename(source_dir))


@contextmanager
def cd(new_dir):
    """
    Changes directories, always return, example:

    with cd('/some/dir'):
        # In some dir
    # Out of some dir
    """

    # Store current directory
    cwd = os.path.abspath(os.getcwd())

    # Move into directory and yield control
    os.chdir(new_dir)

    try:
        yield

    finally:
        # Return to current directory
        os.chdir(cwd)


def template_file(source_path, dest_path, args):
    """
    Use basic python string interpolation to template file.
    """

    # Read file
    text = open(source_path).read()

    # Transform contents
    output = text % args

    # Write out file
    with open(dest_path, 'w') as f:
        f.write(output)


def list_files(path):
    """
    Return a list of all files and directories in the given path, recursively.
    All paths are relative to the given path.
    """

    # Walk directory getting all paths
    raw_results = []

    for root, dirs, files in os.walk(path):
        raw_results.extend([os.path.join(root, d) for d in dirs])
        raw_results.extend([os.path.join(root, f) for f in files])

    # Trim the prefix path from the results
    results = [os.path.relpath(r, path) for r in raw_results]

    # Return the sorted results
    return sorted(results)


def ensure_dir(path):
    """
    Make sure a given directory exists
    """

    if not os.path.exists(path):
        os.makedirs(path)


def touch(path, times=None):
    """
    Create the given file if it doesn't exist, and if does update access times.
    """

    with file(path, 'a'):
        os.utime(path, times)


def load_xpd(path):
    """
    Loads the desired yaml file.
    """

    return yaml.load(open(path))


def match_files(path, pattern):
    """
    Rerusively find all files which match the given pattern.  Results are
    returned as a generator.
    """

    for root, dirs, files in os.walk(path):
        for file_name in files:
            if fnmatch.fnmatch(file_name, pattern):
                full_path = os.path.join(root, file_name)

                yield full_path


class EnvStorage(object):
    """
    Helper class for saving and restoring environment variables.
    """

    def __init__(self, store = False):
        self._env = None

        if store:
            self.store()


    def store(self):
        """
        Store the contents of the current environment variables.
        """

        if self._env:
            raise BaseException("Environment already stored")

        self._env = copy.deepcopy(os.environ)


    def restore(self):
        """
        Restores the previously stored environment variables.
        """

        # Purge new environment variables
        for key in os.environ.keys():
            if not key in self._env:
                del os.environ[key]

        # Restore new variables
        for key, val in self._env.iteritems():
            os.environ[key] = val

        self._env = None


class Version(object):
    def __init__(self, verstr):
        # Determine the epoch
        epochStr = self._parse_epoch(verstr)
        if len(epochStr):
            self.epoch = int(epochStr)
        else:
            self.epoch = 0

        # Determine the release
        self.release = self._parse_release(verstr)

        self.release_parts = self._split_version(self.release)

        # Determine the start and stop index for the complete version string
        # based on the length of the epoch and release
        if len(epochStr):
            startIdx = len(epochStr) + 1
        else:
            startIdx = 0

        if len(self.release):
            stopIdx = len(verstr) - len(self.release) - 1
        else:
            stopIdx = len(verstr)

        self.version = verstr[startIdx:stopIdx]

        self.version_parts = self._split_version(self.version)


    def __cmp__(self, other):
        """
        Compare the whole version in the debian style.
        """

        # Compare epochs
        epochCmp = cmp(self.epoch, other.epoch)

        if 0 != epochCmp:
            return epochCmp

        # Match up pairs
        versionCmp = self._compare_components(self.version_parts, other.version_parts)

        if 0 != versionCmp:
            return versionCmp

        # Compare release if needed (probably need to use the actual method
        return self._compare_components(self.release_parts, other.release_parts)


    @staticmethod
    def _compare_components(a_parts, b_parts):
        """
        Compare the version according to the debian version comparison method.
        """

        def grab(l, idx, gtype, gdefault):
            part = gdefault

            if idx < len(l):
                possible_part = l[idx]

                if isinstance(possible_part, gtype):
                    part = possible_part

            return part

        for idx in xrange(0, max(len(a_parts), len(b_parts))):
            # Grab the non-digit part of the characters
            grab_non_digit = lambda l, idx: grab(l, idx, basestring, '')

            a_str = grab_non_digit(a_parts, idx)
            b_str = grab_non_digit(b_parts, idx)

            # Compare with the special lexicographic version (~,
            # letters, everything else)
            s_cmp = version_string_cmp(a_str, b_str)

            if 0 != s_cmp:
                return s_cmp

            # Consume all digit characters from each item
            grab_digit = lambda l, idx: grab(l, idx, int, 0)

            a_int = grab_digit(a_parts, idx)
            b_int = grab_digit(b_parts, idx)

            # Compare the numbers
            i_cmp = cmp(a_int, b_int)

            if 0 != i_cmp:
                return i_cmp

            idx += 1

        return 0


    def _split_version(self, version_str):
        """
        Split the version up into parts based on the debian version rules.
        """

        # Split up the string based on digit non-digit sections
        raw_parts = re.split('([0-9]+)', version_str)

        # Convert all the digit sections
        digits = set(string.digits)
        parts = []

        for raw_part in raw_parts:
            # Skip empty strings which can occur at the beginning and
            # ending of the list
            if len(raw_part):
                if raw_part[0] in digits:
                    part = int(raw_part)
                else:
                    part = raw_part

                parts.append(part)

        return parts

    def _parse_epoch(self, verstr):
        """
        Try to find the epoch by find the first numeric string, and seeing if
        it's followed by the semi-colon.

        Returns the epoch string.
        """
        epoch = ''

        digits = set(string.digits)

        have_digits = False

        for idx, c in enumerate(verstr):
            is_digit = c in digits

            if is_digit:
                # Still in digits continue as normal
                have_digits = True
            elif have_digits:
                # Digits have stopped, check for semi-colon
                if c == ':':
                    epoch = verstr[0:idx]

                break

        return epoch


    def _parse_release(self, verstr):
        """
        If we can work from the back through the acceptable characters and
        hit a "-" then we have a debian revision

        Returns the release string.
        """

        release = ''

        verstr_reversed = verstr[::-1]

        release_chars = set(string.digits + string.letters + '+.~')

        in_release = False

        for idx, c in enumerate(verstr_reversed):
            is_valid = c in release_chars

            if is_valid:
                # We are in the release
                in_release = True
            elif in_release:
                # Release chars have stopped stopped, check for semi-colon
                if c == '-':
                    release = verstr[len(verstr) - idx:]

                break

        return release


def compare_versions(aStr, bStr):
    """
    Assumes Debian version format:

      [epoch:]upstream_version[-debian_revision]

    Returns:
     -1 : a < b
      0 : a == b
      1 : a > b
    """

    # Compare using the version class
    return cmp(Version(aStr), Version(bStr))


def version_string_cmp(a_s, b_s):
    """
    This is a lexicographically sort modified so that all the letters
    sort earlier than all the non-letters and so that a tilde sorts
    before anything, even the empty string.  Here is an example sorted
    list:

      ['~~', '~~a', '~', '', 'a']
    """

    for i in xrange(0, max(len(a_s), len(b_s))):
        ac = a_s[i] if i < len(a_s) else ''
        bc = b_s[i] if i < len(b_s) else ''

        # Sort tilde and empty string first
        if (ac == '~' and bc != '~'):
            return -1
        elif (ac != '~' and bc == '~'):
            return 1
        elif (ac == '' and bc in string.letters):
             return -1
        elif (ac in string.letters and bc == ''):
            return 1
        else:
            # Normal string comparison
            c = cmp(ac, bc)

            if 0 != c:
                return c

    return 0