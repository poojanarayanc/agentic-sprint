# Day 01 log

**What broke?**
i made a mistake in the message shape, didn't notice that it must be a dict. 
the structure of the messages was wrong therefore. 
there are two types of messages, one by user and the other by model. user is everything other than the model. meaning that's the code I wrote, which is the agent. when we ask 'how many files are there in the folder', model decides that a tool needs to be called. the agent code we write then needs to call the tool and return the result. therefore the messages are alternating, assistant (meaning model)-> user -> assistant -> user... 

**What surprised you?**
the model didn't lie, only gave an estimate when the tool call couldn't go through. 

**One lesson for interviews:**
the API is only a list of messages to be sent to the model, you control the shape and the growth of this. 
subsequent calls are larger. 

**One implication for the team:**
need to know the difference between models and agents. should have idea of writing agent loops with no framworks. 

## Things to try once it works
- Print `len(json.dumps(messages, default=str))` each turn and watch context grow.
- Make a tool fail on purpose. Does the model recover from the `is_error` result?
- Set `max_tokens=50`. What does `max_tokens` as a stop reason do to your loop?
- Ask for something needing 2 tools in parallel. How many tool_use blocks come back in one turn?
