"""Scientific protections carried forward from the stable 1.2.1 release."""

import unittest

import numpy as np

from photon_cruncher.processing.pipeline import process_channel
from photon_cruncher.tests.test_pipeline_equivalence import _golden_session, _golden_settings


class StableRegressionTests(unittest.TestCase):
    def test_added_linear_control_contamination_does_not_change_recovered_signal(self):
        session = _golden_session()
        original = process_channel(
            session, "x405A", "x465A", session.epocs["Cue"], _golden_settings()
        )
        session.streams["x465A"].data += 7 + 3 * session.streams["x405A"].data
        contaminated = process_channel(
            session, "x405A", "x465A", session.epocs["Cue"], _golden_settings()
        )
        np.testing.assert_allclose(original.zall, contaminated.zall, rtol=1e-10, atol=1e-10)
        np.testing.assert_allclose(
            original.zall_smooth, contaminated.zall_smooth, rtol=1e-10, atol=1e-10
        )


if __name__ == "__main__":
    unittest.main()
