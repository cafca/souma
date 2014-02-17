import unittest
import datetime
import sys

from uuid import uuid4

# TODO: make imports work without path tinkering
sys.path.append('/souma')

from synapse.models import Message

class MessageTest(unittest.TestCase):
	
	def setUp(self):
		self.uuid = uuid4().hex
		self.change_time = datetime.datetime.now().isoformat()
		self.message_type = "change_notification"
		
		data = dict({
            "object_type": "Persona",
            "object_id": self.uuid,
            "change": "insert",
            "change_time": self.change_time
		})

		self.message = Message(message_type=self.message_type, data=data)
	
	def test_json(self):
		repr = self.message.json()
		
		#jsonification added timestamp
		self.assertTrue("timestamp" in repr)
		self.assertTrue(self.change_time in repr)
		
		#json encoding complete
		self.assertTrue("message_type" in repr)
		self.assertTrue(self.message_type in repr)
		
		self.assertTrue("data" in repr)
		self.assertTrue("Persona" in repr)
		self.assertTrue(self.uuid in repr)
		
		self.assertTrue("reply_to" in repr)
		
		# jsonification sensitive to new attributes
		self.assertFalse("signature" in repr)
		self.message.send_attributes.append("signature")
		self.message.signature="sincerly yours"
		
		repr = self.message.json()
		self.assertTrue("signature" in repr)
		
	
	def test_read(self):
		pass
		
	def test_sign(self):
		pass

if __name__ == '__main__':
    unittest.main()		