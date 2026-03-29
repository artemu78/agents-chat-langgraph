with open("main.py", "r") as f:
    content = f.read()

content = content.replace(
    'except Exception as e:',
    '''except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                print(f"DEBUG: event was: {repr(event)}")
                for k,v in event.items():
                    print(f"DEBUG: event[{k}] is {type(v)} = {repr(v)}")
            except:
                pass'''
)

with open("main.py", "w") as f:
    f.write(content)
