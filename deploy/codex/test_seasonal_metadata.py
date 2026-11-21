import unittest
from christmas_titles import title_for
from public_metadata import description_for,tags_for,clean_public
class MetadataTests(unittest.TestCase):
    def test_title_is_idempotent_and_christmas_is_first(self):
        for ch,old in [('Quiet Pines Cabin','Cozy Christmas Library & Crackling Fireplace | Sleeping Cat | 3 Hours'),('Little Paris Jazz Cafe','Snowy Paris Café Jazz ❄️ Soft Winter Jazz in Montmartre for Work & Reading | 3 Hours'),('Mountain View Cafe','Snowy Alpine Village | Fireplace | 3 Hours')]:
            title=title_for(ch,old);self.assertEqual(title_for(ch,title),title);self.assertLessEqual(len(title),100);self.assertTrue(title.startswith('Christmas'))
    def test_public_copy_has_no_provider_links_or_ai_boilerplate(self):
        old='A warm room.\n\nThe visuals are AI-created.\nFireplace audio: Lit Fireplace by lurpsis.\nhttps://pixabay.com/sound-effects/household-lit-fireplace-6307/'
        for ch in ['Little Paris Jazz Cafe','Quiet Pines Cabin','Mountain View Cafe']:
            desc=description_for(ch,'Christmas Cozy Cabin | Fireplace | 3 Hours',old)
            self.assertNotIn('pixabay',desc.lower());self.assertNotIn('http',desc);self.assertNotIn('AI-created',desc)
            self.assertEqual(description_for(ch,'Christmas Cozy Cabin | Fireplace | 3 Hours',desc),desc)
    def test_audio_descriptions_are_channel_specific(self):
        jazz=description_for('Little Paris Jazz Cafe','Christmas Paris Café Jazz')
        self.assertIn('instrumental jazz',jazz);self.assertNotIn('fireplace crackle only',jazz)
        for ch in ['Quiet Pines Cabin','Mountain View Cafe']:
            d=description_for(ch,'Christmas Cozy Room')
            self.assertIn('no music',d);self.assertNotIn('purring',d)
    def test_exhale_is_untouched(self):
        self.assertEqual(title_for('Exhale to Sleep','Test original title'),'Test original title')
        self.assertEqual(description_for('Exhale to Sleep','Title','Original text'),'Original text')
    def test_tag_budget_and_unique_scene_keywords(self):
        for ch in ['Little Paris Jazz Cafe','Quiet Pines Cabin','Mountain View Cafe']:
            tags=tags_for(ch,'Christmas Edinburgh Café Jazz | 3 Hours')
            self.assertEqual(len(tags),len(set(tags)))
            self.assertLessEqual(sum(len(t)+2 for t in tags)+len(tags)-1,490)
            self.assertTrue(any('christmas' in t for t in tags))
if __name__=='__main__':unittest.main()
