import unittest

from chain.embed_queue import EmbedQueue


class EmbedQueueQualityGateTest(unittest.TestCase):
    def test_has_trusted_description_uses_derived_vlm_status(self):
        self.assertTrue(EmbedQueue._has_trusted_description({"vlmStatus": "healthy"}))
        self.assertTrue(EmbedQueue._has_trusted_description({"vlm_status": "healthy"}))
        self.assertFalse(EmbedQueue._has_trusted_description({"vlmStatus": "review"}))
        self.assertFalse(EmbedQueue._has_trusted_description({}))
