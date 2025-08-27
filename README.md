## HOW DO YOU SETUP YOUR TWILIO ACCOUNT WITH YOUR APP
Steps are given below-
first run "pip install -r requirement.txt" to install all the required files
1- Go to TWILIO account dashboard
2- select Develop tap and go to active numbers under manage section in #phone numbers tab
3- click the active number and go to Messaging Configuration by selecting configure tab
4- on " A message comes in " and "A call comes in section"  select webhook and go to URL copy the local ip where the app is running and put it in the URL box {if it has been deployed on cloud server use that link}
5- run your python app "python app.py " 
6 - save Configuration
