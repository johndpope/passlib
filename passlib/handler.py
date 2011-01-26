"""passlib.handler - code for implementing handlers, and global registry for handlers"""
#=========================================================
#imports
#=========================================================
from __future__ import with_statement
#core
import inspect
import re
import hashlib
import logging; log = logging.getLogger(__name__)
import time
import os
#site
#libs
from passlib.utils import abstract_class_method, classproperty, H64_CHARS, getrandstr, rng, Undef
#pkg
#local
__all__ = [
    #global registry
    'register_crypt_handler',
    'get_crypt_handler',
    'list_crypt_handlers'

    'is_crypt_handler',
    'is_ext_crypt_handler',

    #framework for implementing handlers
    'CryptHandler',
    'ExtCryptHandler',
]

#=========================================================
#global registry
#=========================================================
_handler_map = {} #dict mapping names & aliases -> crypt algorithm instances
_name_set = set() #list of keys in _handler_map which are names not aliases

def register_crypt_handler(obj):
    "register CryptHandler handler"
    global _handler_map, _name_set

    if not is_crypt_handler(obj):
        raise TypeError, "object does not appear to be CryptHandler handler: %r" % (obj,)

    name = obj.name
    _validate_name(name)

    if name in _name_set:
        log.warning("overriding previous handler registered to name %r: %r", name, _handler_map[name])
##        raise ValueError, "handler already registered for name %r: %r" % (name, _handler_map[name])

    _handler_map[name] = obj
    _name_set.add(name)

    for alias in obj.aliases:
        _validate_name(alias)
        if alias not in _name_set:
            _handler_map[alias] = obj

    log.info("registered crypt handler: obj=%r name=%r aliases=%r", obj, obj.name, obj.aliases)

def _validate_name(name):
    "validate crypt algorithm name"
    if not name:
        raise ValueError, "name/alias empty: %r" % (name,)
    if name.lower() != name:
        raise ValueError, "name/alias must be lower-case: %r" %(name,)
    if re.search("[^-a-zA-Z0-9]",name):
        raise ValueError, "names & aliases must consist of a-z, 0-9, A-Z: %r" % (name,)
    return True

def get_crypt_handler(name, default=Undef):
    "resolve crypt algorithm name / alias"
    global _handler_map
    if default is Undef:
        return _handler_map[name]
    else:
        return _handler_map.get(name, default)

def list_crypt_handlerss():
    "return sorted list of all known crypt algorithm names"
    global _name_set
    return sorted(_name_set)

#==========================================================
#other helpers
#==========================================================
def is_crypt_handler(obj):
    "check if obj following CryptHandler protocol"
    #NOTE: this isn't an exhaustive check of all required attrs,
    #just a quick check of the most uniquely identifying ones
    return all(hasattr(obj, name) for name in (
        "name", "verify", "encrypt", "identify",
        ))

def is_ext_crypt_handler(obj):
    "check if obj following ExtCryptHandler protocol"
    #NOTE: this isn't an exhaustive check of all required attrs,
    #just a quick check of the most uniquely identifying ones
    return all(hasattr(obj, name) for name in (
        "name", "verify", "encrypt", "identify", "parse", "render"
        ))

#==========================================================
#base interface for all the crypt algorithm implementations
#==========================================================
class CryptHandler(object):
    """base class for implementing a password algorithm.

    The following should be filled out for all crypt algorithm subclasses.
    Additional methods, attributes, and features may vary.

    Informational Attributes
    ========================
    .. attribute:: name

        This should be a globally unique name to identify
        the hash algorithm with.

    .. attribute:: salt_bytes

        This is a purely informational attribute
        listing how many bytes are in the salt your algorithm uses.

    .. attribute:: hash_bytes

        This is a purely informational attribute
        listing how many bytes are in the cheksum part of your algorithm's hash.

    .. note::

        Note that all the bit counts should measure
        the number of bits of entropy, not the number of bits
        a given encoding takes up.

    .. attribute:: has_salt

        This is a virtual attribute,
        calculated based on the value of the salt_bytes attribute.
        It returns ``True`` if the algorithm contains any salt bytes,
        else ``False``.

    .. attribute:: secret_chars

        Number of characters in secret which are used.
        If ``None`` (the default), all chars are used.
        BCrypt, for example, only uses the first 55 chars.

    .. attribute:: has_rounds

        This is a purely informational attribute
        listing whether the algorithm can be scaled
        by increasing the number of rounds it contains.
        It is not required (defaults to False).

    .. attribute:: has_named_rounds

        If this flag is true, then the algorithm's
        encrypt method supports a ``rounds`` keyword
        which (at the very least) accepts the following
        strings as possible values:

            * ``fast`` -- number of rounds will be selected
                to provide adequate security for most user accounts.
                This is retuned perodically to take around .25 seconds.

            * ``medium`` -- number of rounds will be selected
                to provide adequate security for most root/administrative accounts
                This is retuned perodically to take around .75 seconds.

            * ``slow`` -- number of rounds will be selected
                to require a large amount of calculation time.
                This is retuned perodically to take around 1.5 seconds.

        .. note::
            Last retuning of the default round sizes was done
            on 2009-07-06 using a 2ghz system.

    Common Methods
    ==============
    .. automethod:: identify

    .. automethod:: encrypt

    .. automethod:: verify

    Implementing a new crypt algorithm
    ==================================
    Subclass this class, and implement :meth:`identify`
    and :meth:`encrypt` so that they implement your
    algorithm according to it's documentation
    and the specifications of the methods themselves.
    You must also specify :attr:``name``.
    Optionally, you may override :meth:`verify`
    and set various informational attributes.

    """

    #=========================================================
    #class attrs
    #=========================================================

    #---------------------------------------------------------
    #registry
    #---------------------------------------------------------
    name = None #globally unique name to identify algorithm. should be lower case and hyphens only
    aliases = () #optional list of aliases (other names) this hash should be recognized by
    context_kwds = () #tuple of additional kwds required for any encrypt / verify operations; eg "realm" or "user"
    setting_kwds = () #tuple of additional kwds that encrypt accepts for configuration algorithm; eg "salt" or "rounds"

    #---------------------------------------------------------
    #optional informational attributes
    #---------------------------------------------------------
    secret_chars = -1 #max number of chars of secret that are used in hash. -1 if all chars used.

    #---------------------------------------------------------
    #algorithm rounds information - only required if alg supports rounds
    #---------------------------------------------------------
    default_rounds = None #default number of rounds to use if none specified (can be name of a preset)
    min_rounds = None #minimum number of rounds (smaller values silently ignored)
    max_rounds = None #maximum number of rounds (larger values silently ignored)

    #=========================================================
    #1.4 frontend interface
    #=========================================================

    @classmethod
    def genconfig(cls, **settings):
        """return configuration string encoding settings

        Many hashes have configuration options,
        and support a configuration string which encodes them.
        (this is usually an abbreviated version of their encoded hash format).
        If the hash does not support configuration options,
        this should return ``None``.

        :param settings:
            this function takes in keywords as specified in :attr:`setting_kwds`.

        :raises ValueError:
            * if any configuration options are required, missing, AND
              a default value cannot be autogenerated.
              (for example: salt strings should be autogenerated if not specified).
            * if any configuration options are invalid, and cannot be
              normalized in a reasonble manner (eg: salt strings clipped to maximum size).

        :returns:
            configuration string, or ``None`` if no configuration used by hash.
        """
        if cls.setting_kwds:
            raise NotImplementedError, "classes with config kwds must implement genconfig()"
        if config:
            raise TypeError, "%s has no configuration options" % (cls,)
        return None

    @abstract_class_method
    def genhash(cls, secret, config, *context_args, **context_kwds):
        """encrypt secret to hash

        takes in a password, optional configuration string,
        and any required contextual information the algorithm needs,
        and returns the encoded hash strings.

        :arg secret: string containing the password to be encrypted
        :arg config:
            configuration string to use when encrypting secret.

            if the algorithm does not have any configuration options,
            these value can be ignored entirely. otherwise...

            * existing hash - algorithm should extract configuration
              from an existing hash (such as the one stored when password was set).
            * new config string - algorithm should recognize config strings
              returned by :meth:`genconfig`. this does not apply if genconfig
              always returns ``None``.
            * ``None`` - if no configuration is specified, but one is needed,
              the algorithm should automatically generate a new configuration
              by calling :meth:`genconfig`.

        :param context:
            All other keywords must be external contextual information
            required by the algorithm to create the hash. If any,
            these kwds must be specified in :attr:`context_kwds`.

        :raises ValueError:
            * if the configuration string is invalid / not recognized.
            * if the secret contains a forbidden character (rare, but some algorithms have limitations, eg: forbidding null characters)
            * if the contextual information is invalid / missing

        :returns:
            encoded hash matching specified secret, config, and context.
        """

    @classmethod
    def identify(cls, hash):
        """identify if a hash string belongs to this algorithm.

        :arg hash:
            the hash string to check

        :returns:
            ``True`` if provided hash string is handled by
            this class, otherwise ``False``.
            If hash is ``None``, should return ``False``.
        """
        #NOTE: this default method is going to be *really* slow for most implementations,
        #they should override it. but if genhash() conforms to the specification, this will do.
        if cls.context_kwds:
            raise NotImplementedError, "classes with context kwds must implement identify()"
        if not hash:
            return False
        try:
            cls.genhash("stub", hash)
        except ValueError:
            return False
        return True

    @classmethod
    def verify(cls, secret, hash, *context_args, **context_kwds):
        """verify a secret against an existing hash.

        This checks if a secret matches against the one stored
        inside the specified hash.

        :param secret:
            A string containing the secret to check.
        :param hash:
            A string containing the hash to check against.

        :param context:
            Any additional keywords will be passed to the encrypt
            method. These should be limited to those listed
            in :attr:`context_kwds`.

        :raises ValueError:
            * if the hash not specified
            * if the hash does not match this algorithm's hash format

        :returns:
            ``True`` if the secret matches, otherwise ``False``.
        """
        #NOTE: methods whose hashes have multiple encodings should override this,
        # as the hash will need to be normalized before comparing via string equality.
        # alternately, the ExtCryptHandler class provides a more flexible framework.

        #ensure hash was specified - genhash() won't throw error for this
        if not hash:
            raise ValueError, "no hash specified"

        #the genhash() implementation for most setting-less algorithms
        #simply ignores the config string provided; whereas most
        #algorithms with settings have to inspect and validate it.
        #therefore, we do this quick check IFF it's setting-less
        if not cls.setting_kwds and not cls.identify(hash):
            raise ValueError, "not a %s hash" % (cls.name,)

        #do simple string comparison
        return hash == cls.genhash(secret, hash, *context_args, **context_kwds)

    #=========================================================
    #legacy 1.3 frontend interface
    #=========================================================

    @classmethod
    def encrypt(cls, secret, *context_args, **context_and_settings):
        """encrypt secret, returning resulting hash string.

        :arg secret:
            A string containing the secret to encode.
            Unicode behavior is specified on a per-hash basis,
            but the common case is to encode into utf-8
            before processing.

        :param context_and_settings:
            All other keywords are algorithm-specified,
            and should be listed in :attr:`setting_kwds`
            and :attr:`context_kwds`.

            Common keywords include ``salt`` and ``rounds``.

        :raises ValueError:
            * if settings are invalid and not correctable.
              (eg: provided salt contains invalid characters / length).

            * if a context kwd contains an invalid value, or was required
              but omitted.

            * if secret contains forbidden characters (e.g: des-crypt forbids null characters).
              this should rarely occur, since most modern algorithms have no limitations
              on the types of characters.

        :returns:
            Hash encoded in algorithm-specified format.
        """
        if cls.context_kwds:
            #extract context kwds
            context = dict(
                (k,context_and_settings.pop(k))
                for k in cls.context_kwds
                if k in context_and_settings
            )
            #generate config string
            config = cls.genconfig(**context_and_settings)
            #run through genhash
            return cls.genhash(secret, config, *context_args, **context)
        else:
            #let genhash create new config if needed.
            return cls.genhash(secret, None, *context_args, **context_and_settings)

    #=========================================================
    #eoc
    #=========================================================

#=========================================================
#
#=========================================================
class ExtCryptHandler(CryptHandler):
    """class providing an extended handler interface,
    allowing manipulation of hash & config strings.

    About
    -----
    this extended interface adds methods for parsing and rendering
    a hash or config string to / from a dictionary of components.

    this interface is generally easier to use when *implementing* hash
    algorithms, and as such is used through passlib. it's kept separate
    from :class:`CryptHandler` itself, since it's features are not typically
    required for user-facing purposes.

    Usage
    -----
    when implementing a hash algorithm...

    subclasses must implement:

        * parse()
        * render()
        * genconfig()
        * genhash()

    subclasses may optionally implement more efficient versions of
    these functions, though the defaults should be sufficient:

        * identify()
        * verify()

    some helper methods are provided for implementing genconfig, genhash & verify.
    """

    #=========================================================
    #class attrs
    #=========================================================

    #---------------------------------------------------------
    # _norm_salt() configuration
    #---------------------------------------------------------

    salt_chars = None #fill in with (maxium) number of salt chars required, and _norm_salt() will handle truncating etc
    salt_charset = H64_CHARS #helper used when generating salt
    salt_charpat = None #optional regexp used by _norm_salt to validate salts

    #override only if minimum number of salt chars is different from salt_chars
    @classproperty
    def min_salt_chars(cls):
        return cls.salt_chars

    #=========================================================
    #parsing routines
    #=========================================================

    @abstract_class_method
    def parse(cls, hash):
        """parse hash or config into dictionary.

        :arg hash: the hash/config string to parse

        :raises ValueError:
            If hash/config string is empty,
            or not recognized as belonging to this algorithm

        :returns:
            dictionary containing a subset of the keys
            specified in :attr:`setting_kwds`.

            commonly used keys are ``salt``, ``rounds``.

            If and only if the string is a hash, the dict should also contain
            the key ``checksum``, mapping to the checksum portion of the hash.

        .. note::
            Specific implementations may perform anywhere from none to full
            validation of input string; the primary goal of this method
            is to parse settings from single string into kwds
            which will be recognized by :meth:`render` and :meth:`encrypt`.

            :meth:`encrypt` is where validation of inputs *must* be performed.
        """

    @abstract_class_method
    def render(cls, checksum, **settings):
        """render hash from checksum & settings (as returned by :meth:`parse`).

        :param checksum:
            Encoded checksum portion of hash.

        :param settings:
            All other keywords are algorithm-specified,
            and should be listed in :attr:`setting_kwds`.

        :raises ValueError:
            If any values are not encodeable into hash.

        :raises NotImplementedError:
            If checksum is omitted and the algorithm
            doesn't have any settings (:attr:`setting_kwds` is empty),
            or doesn't support generating "salt strings"
            which contain all configuration except for the
            checksum itself.

        :returns:
            if checksum is specified, this should return a fully-formed hash.
            otherwise, it should return a config string containing
            the specified inputs.

        .. note::
            Specific implementations may perform anywhere from none to full
            validation of inputs; the primary goal of this method
            is to render the settings into a single string
            which will be recognized by :meth:`parse`.

            :meth:`encrypt` is where validation of inputs *must* be performed.
        """

    #=========================================================
    #identify helpers
    #=========================================================

    #NOTE: this default identify is usually sufficient,
    # though implementations may override it with an even faster check,
    # such as a specific string size & prefix

    @classmethod
    def identify(cls, hash):
        try:
            cls.parse(hash)
        except ValueError:
            return False
        return True

    #=========================================================
    #genconfig helpers
    #=========================================================

    #NOTE: genconfig() must still be implemented,
    # but helper functions provided below

    #render() is usually needed

    #----------------------------------------------------------------
    #normalization helpers rounds
    #----------------------------------------------------------------
    @classmethod
    def _norm_rounds(cls, rounds):
        """helper routine for normalizing rounds

        * falls back to :attr:`default_rounds`
        * raises ValueError if no fallback
        * clips to min_rounds / max_rounds
        * issues warnings if rounds exists min/max

        :returns: normalized rounds value
        """
        if not rounds:
            rounds = cls.default_rounds
            if not rounds:
                raise ValueError, "rounds must be specified explicitly"
        mx = cls.max_rounds
        if mx and rounds > mx:
            warn("%s algorithm does not allow more than %d rounds: %d", mx, rounds)
            rounds = mx
        mn = cls.min_rounds
        if mn and rounds < mn:
            warn("%s algorithm does not allow less than %d rounds: %d", mn, rounds)
            rounds = mn
        return rounds

    #----------------------------------------------------------------
    #normalization helpers for salts
    #----------------------------------------------------------------
    @classmethod
    def _gen_salt(cls):
        """helper routine to generate salt, used by _norm_salt"""
        return getrandstr(rng, cls.salt_charset, cls.salt_chars)

    @classmethod
    def _validate_salt_chars(cls, salt):
        "validate chars in salt, used by _norm_salt"
        cs = cls.salt_charset
        for c in salt:
            if c not in cs:
                raise ValueError, "invalid character in %s salt: %r"  % (cls.name, c)
        return salt

    @classmethod
    def _norm_salt(cls, salt):
        """helper routine for normalizing salt

        required salt_charset & salt_chars attrs to be filled in,
        along with optional min_salt_chars attr (defaults to salt_chars).

        * generates salt if none provided
        * clips salt to maximum length of salt_chars

        :raises ValueError:
            * if salt contains chars that aren't in salt_charset.
            * if salt contains less than min_salt_chars characters.

        :returns:
            resulting or generated salt
        """
        if salt is None:
            return cls._gen_salt()

        salt = cls._validate_salt_chars(salt)

        mn = cls.min_salt_chars
        assert mn is not None, "cls.min_salt_chars not set"
        if len(salt) < mn:
            raise ValueError, "%s salt must be at least %d chars" % (cls.name, mn)

        mx = cls.salt_chars
        assert mx is not None, "cls.salt_chars not set"
        if len(salt) > mx:
            #automatically clip things to specified number of chars
            return salt[:mx]
        else:
            return salt

    #=========================================================
    #genhash helper functions
    #=========================================================

    #NOTE: genhash() must still be implemented,
    # but helper functions are provided below for common workflows...

    #----------------------------------------------------------------
    #for handlers which normalize config string and hand off to external library
    #----------------------------------------------------------------
    @classmethod
    def _prepare_config(cls, config):
        """normalize config string provided to genhash; return new config string"""
        if not cls.setting_kwds:
            return None
        if config:
            kwds = cls.parse(config)
            kwds.pop("checksum", None)
            return cls.genconfig(**kwds)
        else:
            return cls.genconfig()

    #----------------------------------------------------------------
    #for handlers which implement the guts of the process directly
    #----------------------------------------------------------------

    # parse() and render() are usually used as well

    @classmethod
    def _prepare_parsed_config(cls, config):
        """normalize config string provided to genhash; return parsed settings"""
        if not cls.setting_kwds:
            return {}
        return cls.parse(cls._prepare_config(config))

    #=========================================================
    #verify helper functions
    #=========================================================

    #NOTE: the default verify method provided here works for most cases,
    # though some handlers will want to implement norm_hash() if their
    # hash has multiple equivalent representations (eg: case insensitive)

    @classmethod
    def verify(cls, secret, hash, *context_args, **context_kwds):
        if not hash:
            raise ValueError, "no hash specified"
        if not cls.identify(hash):
            raise ValueError, "not a %s hash" % (cls.name,)
        hash = cls.norm_hash(hash)
        return hash == cls.genhash(secret, hash, *context_args, **context_kwds)

        #alt implementation...
        ##info = cls.parse(hash)
        ##if not info.get('checksum'):
        ##  raise ValueError, "hash lacks checksum"
        ##other = cls.genhash(secret, hash, *context_args, **context_kwds)
        ##other_info = cls.parse(other)
        ##return info['checksum'] == other_info['checksum']

    @classmethod
    def norm_hash(cls, hash):
        "helper for default verify method"
        #NOTE: this only needs implementing if hash has multiple valid encodings (eg case insensitive)
        return hash

    #=========================================================
    #eoc
    #=========================================================

#=========================================================
# eof
#=========================================================
