from algo.core.calendar import nse
from algo.data.providers.base import DataProvider, ParseError
from algo.data.providers.nse_bhavcopy import NseBhavcopy


def test_bhavcopy_conforms_to_provider_protocol_and_parse_error_is_exception():
    assert isinstance(NseBhavcopy(lambda u: b"", nse()), DataProvider)
    assert not isinstance(object(), DataProvider)
    assert issubclass(ParseError, Exception)
