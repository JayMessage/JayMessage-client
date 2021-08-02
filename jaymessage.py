'''
MIT License

Copyright (c) 2021 JayMessage

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''

from zeep import Client, Settings, xsd
from zeep.cache import SqliteCache
from zeep.transports import Transport
from bs4 import BeautifulSoup
import sys
import signal
import time
import keyring
from datetime import datetime

versionstring = '0.1.0-alpha'

def signal_handler(sig, frame): # lets us handle CTRL-C in a nice way
        print('Program was stopped manually.')
        sys.exit(0)
signal.signal(signal.SIGINT, signal_handler)
transport = Transport(cache=SqliteCache())

client = Client(
    'https://android.services.jpay.com/JPayCitizensWS/JPayCitizensService.asmx?wsdl', ## handles account operations, such as logging in
    transport=transport,
    settings = Settings(strict=False, xml_huge_tree=True,raw_response=True)
)

mailClient = Client(
    'https://android.services.jpay.com/JPayMailWS/JPayEMessageService.asmx?WSDL', ## handles mail operations, such as reading or sending letters
    transport=transport,
    settings = Settings(strict=False, xml_huge_tree=True,raw_response=True)
)

client.transport.session.headers.update({'user-agent': 'ksoap2-android/2.6.0+;version=3.6.4'})

def getCredentials(method): ## capture login creds from user interactively or from keyring

    while True:
        if method != 'interactive':
            try:
                f = open('config.txt','r')
                username = f.readline().strip()
                f.close()
                if (keyring.get_password('JayMessage', username) == None):
                    raise('The keyring did not provide a password.')

                password = keyring.get_password('JayMessage', username)
                
                return(username, password, 'keyring') ## return credentials and source
            except:
                print('Could not load credentials from keyring. We\'ll ask if you want to save your credentials later.')
                try:
                    f.close()
                except:
                    pass ## bad error handling :^)
                method = 'interactive'

        else:
            print('Username: ', end='')
            username = input()
            print('Password: ', end='')
            password = input()
            return(username,password,'interactive') ## return credentials and source

inLoginDetails =	{ ## headers required to make SOAP requests to JPay
    "EntityID": "MOBILEAPP",
    "EntityType": "ExternalPartner",
    "APIUser": "Mobileapi_10082015",
    "APIPassword": "a3cv5A8ZSxbrPfvU4D7DMvcGugg7Pfvq",
    "Originator": "Mobile_Android",
    "outKeepSessionAliveInterval": 3600,
    "Version": 'NotSpecified',
    'InmateSecurityQuestionVersionNumber': 0,
    'LocationSecurityQuestionVersionNumber': 0
}

savedCredentials = getCredentials('keyring')
username = savedCredentials[0]
password = savedCredentials[1]

while True:

    loginreq = client.service.RefreshCustomerLoginToken(inLoginDetails,username,password)
    
    while BeautifulSoup(loginreq.text, 'xml').find('success').text == 'false': ## Error handling for failed logins
        
        print('Login failed!')
        print('Reason from JPay: ' + BeautifulSoup(loginreq.text, 'xml').find('ErrorMessage').text)
        print('JPay error code: ' + BeautifulSoup(loginreq.text, 'xml').find('ErrorCodeString').text)

        userRetry = None

        while userRetry != 'Y' and userRetry != 'N':
            print('Retry? (Y/N): ',end='')
            userRetry = input().upper()
            if userRetry == 'Y':
                savedCredentials = getCredentials('interactive')
                username = savedCredentials[0]
                password = savedCredentials[1]
                userRetry = None
                break
            elif userRetry == 'N':
                print('Exiting...')
                sys.exit(1)
            else:
                print('Invalid entry.')

    if BeautifulSoup(loginreq.text, 'xml').find('success').text == 'true':
        print('Signed in successfully!')
        
        saveCredentialsPrompt = None
        while (saveCredentialsPrompt == None) and (savedCredentials[2] == 'interactive'):
            print('Save credentials? Your password will be saved in your system keyring. (Y/N): ',end='')
            saveCredentialsPrompt = input().lower()
            if saveCredentialsPrompt == 'y':
                try:
                    f = open("config.txt", "w")
                    f.write(username + '\n')
                    f.close()
                    keyring.set_password('JayMessage', username, password)
                    f = open("config.txt", "r")

                    if (f.readline().strip() == username) or (keyring.get_password("JayMessage", username) != None): ## double-check that we wrote to config and saved pw in keyring
                        
                        try:
                            f.close()
                            print('Your credentials have been saved.')
                        except:
                            pass
                    else:
                        raise Exception(CredentialIOError)
                except:
                    print('Your credentials could not be saved.')
                    try:
                        f.close()
                    except:
                        pass
                    break
            elif saveCredentialsPrompt == 'n':
                print('Credentials will not be saved.')

            else:
                print('Invalid entry.')
                saveCredentialsPrompt = None
    break

authtoken = loginreq.headers.get('ws_auth_token') ## required in header to authenticate; we add this to our headers below:
client.transport.session.headers.update({'user-agent': 'ksoap2-android/2.6.0+;version=3.6.4','ws_auth_token': authtoken})
mailClient.transport.session.headers.update({'user-agent': 'ksoap2-android/2.6.0+;version=3.6.4','ws_auth_token': authtoken})

userLoginID = int(BeautifulSoup(loginreq.text, 'xml').find('UserId').text) ## get loginID, required for most API calls
                                               
retriveAfterThisLetter = 0 ## COMMENT OUTDATED if set to 0, JPay returns the last 50 messages received. If given a letter ID, it returns the 50 messages before that letter.

stampCountResponse = mailClient.service.GetAgenciesAndStampCountsByUserId(inLoginDetails,userLoginID)

stampDict = {}

facilityStamps = BeautifulSoup(stampCountResponse.text, 'xml').find('StampCountByFacility')

print('Retrieving messages...')
mailParsingPasses = 0
letterCount=0
while True:

##    dataset = mailClient.service.GetCustomerInboxFolderByLetterAmount(inLoginDetails,userLoginID,retriveAfterThisLetter,'false','false',)
    dataset          = mailClient.service.GetCustomerInboxFolder(inLoginDetails,userLoginID,'false','false',)
    datasetArchived  = mailClient.service.GetCustomerInboxFolder(inLoginDetails,userLoginID,'true','false',)
    mailList         = BeautifulSoup(dataset.text, 'xml')
    archivedMailList = BeautifulSoup(datasetArchived.text, 'xml')
    mailProcessor = mailList.find('JPayUserEmailInbox')
    
    while True:

        if mailParsingPasses == 1:
            mailProcessor = archivedMailList.find('JPayUserEmailInbox')
        elif mailParsingPasses == 2:
            break

        while mailProcessor != None: ## mailProcessor.nextSibling will return None if there is nothing next; this is an easy way to tell we're done
            letterCount += 1
            sentTime = mailProcessor.find('createdDate').text
            recipientName = mailProcessor.find('sRecipientName').text
            letterID = int(mailProcessor.find('uniqueID').text)

            if mailProcessor.find('ReadStatus').text == '1': ## this makes much more sense to convert to bool
                readStatus = True
            else:
                readStatus = False
            
            messageContent = mailProcessor.find('Message').text
            inmateID = mailProcessor.find('sInmateID').text
            facilityID = mailProcessor.find('iFacilityID').text

            if mailProcessor.find('EmailHasAttachments').text == 'true': ## this makes much more sense to convert to bool
                emailHasAttachments = True
            elif mailProcessor.find('EmailHasAttachments').text == 'false':
                emailHasAttachments = False
            else:
                emailHasAttachments = True
            
            letterPreviewNameBase = 'letterPreview' + str(letterCount)
            
            try:
                newPreviewDict[letterPreviewNameBase + 'sentTime'] = sentTime
                newPreviewDict[letterPreviewNameBase + 'recipientName'] = recipientName
                newPreviewDict[letterPreviewNameBase + 'letterID'] = letterID
                newPreviewDict[letterPreviewNameBase + 'readStatus'] = readStatus
                newPreviewDict[letterPreviewNameBase + 'Message'] = messageContent
                newPreviewDict[letterPreviewNameBase + 'inmateID'] = inmateID
                newPreviewDict[letterPreviewNameBase + 'facilityID'] = facilityID
                newPreviewDict[letterPreviewNameBase + 'emailHasAttachments'] = emailHasAttachments
                letterList.append(letterID)
                mailProcessor = mailProcessor.nextSibling
                if mailProcessor == None:
                    mailParsingPasses += 1
                if readStatus == False: ## keep track of unread letters, to alert user later
                    unreadLetters.append(letterID)

            except:
                newPreviewDict = {} ## if the above failed, we probably don't have a dict yet
                letterList = [] ## list of all letters in memory, by letter ID
                unreadLetters = []
                letterCount -= 1 ## this interation doesn't count

    print('Checking stamps...')
    while facilityStamps != None:
        facilityStampCount = int(facilityStamps.find('UStamps').text)
        agencyName = facilityStamps.find('AgencyName').text.strip()
        facilityStamps = facilityStamps.nextSibling

        stampDict[agencyName] = facilityStampCount


    print('Retrieving contacts...')
    inmateListRaw = client.service.GetCitizenContactList(inLoginDetails,userLoginID)
    inmateListxml = BeautifulSoup(inmateListRaw.text, 'xml').find('LimitedOffender')
    contactDict = {}
    while inmateListxml != None:
        contactName = inmateListxml.find('FirstName').text + ' ' + inmateListxml.find('LastName').text
        contactID = int(inmateListxml.find('InmateUniqueId').text)
        inmateListxml = inmateListxml.nextSibling

        contactDict[contactName] = contactID

#        print('Checking VideoGrams...')
##videoGramRequestRaw = mailClient.service.GetCustomerVMailLetterIDsFromMobile(inLoginDetails,'Mobile',userLoginID,'false','false',)
##videoGramRequest = BeautifulSoup(videoGramRequestRaw.text, 'xml').find('StampCountByFacility')
##        while videoGramRequest != None:
            

    while True:
        print(str(len(letterList)) + ' letters loaded.')
        print('You have ' + str(len(unreadLetters)) + ' unread messages.' + '\n')
        for i in stampDict:
            print(i + ' stamps: ' + str(stampDict[i]))
            
        print('\n' + 'Contacts:')
        for i in contactDict:
            print(str(i))
        
        print('Ready for commands. Type a number between 1-' + str(len(letterList)) + ' to view the message.')
        print('Type \'a\' or \'archive\' to save all messages to a file.')
        print('Type \'q\' or \'quit\' to exit.')
        print('> ',end='')
        selectedLetter = input().lower()

        if (selectedLetter == 'q') or (selectedLetter == 'quit') or (selectedLetter == 'exit'):
            print('Exiting.')
            sys.exit(0)

        elif (selectedLetter == 'a') or (selectedLetter == 'archive'):
            archiveFile = open('jpay-archive-' + datetime.now().strftime('%Y-%m-%d-%H%M%S') + '.txt','w')
            userInput = None
            while userInput == None:
                print('Archive will be saved to: ' +  archiveFile.name)
                print('Is that okay? (Y/N): ',end='')
                userInput = input().lower()
                if userInput == 'y':
                    q = len(letterList)
                    archiveFile.write('JayMessage ' + versionstring + ' archive' + '-' + datetime.isoformat(datetime.now()) + '\n')
                    for x in letterList:

                        if newPreviewDict.get('letterPreview' + str(q) + 'emailHasAttachments') == False:
                            humanReadableAttachmentStatus = 'No'
                        else:
                            humanReadableAttachmentStatus = 'Yes'
                        
                        archiveFile.write('-------------------------' + '\n')
                        archiveFile.write('Sender: ' + newPreviewDict.get('letterPreview' + str(q) + 'recipientName') + '\n')
                        archiveFile.write('Date: '   + newPreviewDict.get('letterPreview' + str(q) + 'sentTime') + '\n')
                        archiveFile.write('Attachment: '   + humanReadableAttachmentStatus + '\n' + '\n')
#                        archiveFile.write('Content:' + '\n' + '\n')
                        archiveFile.write(newPreviewDict.get('letterPreview' + str(q) + 'Message') + '\n')
#                        archiveFile.write('-------------------------' + '\n')
                        q-= 1
                    archiveFile.close()
                    print('Archive saved.')
                elif userInput == 'n':
                    print('No archive will be created.')
                else:
                    print('Invalid entry.')
                    userInput = None

        elif 1 <= int(selectedLetter) <= len(letterList):

            print('-------------------------')
            print('Sender: ' + newPreviewDict.get('letterPreview' + selectedLetter + 'recipientName'))
            print('Date: '   + newPreviewDict.get('letterPreview' + selectedLetter + 'sentTime'))
            print('Content:')
            print(newPreviewDict.get('letterPreview' + selectedLetter + 'Message'))
            print('-------------------------')

        else:
            print('Please enter a valid command.')
