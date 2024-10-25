from hubspot import HubSpot
from hubspot.crm.contacts import SimplePublicObjectInput
from hubspot.crm.contacts.exceptions import ApiException as ContactsApiException, UnauthorizedException as ContactsUnauthorizedException
from hubspot.crm.properties.exceptions import ApiException as PropertiesApiException, UnauthorizedException as PropertiesUnauthorizedException
from .abstract import AbstractAction
from navconfig import config
from ..exceptions import ConfigError, FailedAuth 


HUBSPOT_TOKEN = config.get('HUBSPOT_TOKEN')

class Hubspot(AbstractAction):
    """Hubspot.

    Interact with HubSpot API using Actions
    """
    def __init__(self, *args, **kwargs):
        super(Hubspot, self).__init__(*args, **kwargs)
        self.token = self._kwargs.pop('token', HUBSPOT_TOKEN)
        self.client = HubSpot(api_key=self.token)

    async def run(self):
        pass

    def get_contacts(self):
        """
        Retrieve details of a all contacts
        
        :return: List of Contacts details if found, else None.
        """
        try:
            after = None
            all_contacts = []
            while True:
                response = self.client.crm.contacts.basic_api.get_page(limit=100, after=after)
                for contact in response.results:
                    all_contacts.append(contact.to_dict())
                if not response.paging or not response.paging.next:
                    break
                after = response.paging.next.after
            return all_contacts
        except ContactsUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to get contacts: {e.body}") from e
        except ContactsApiException as e:
            raise ConfigError(f"Hubspot: Error getting contacts: {e.body}") from e

    def get_contact(self, contact_id: str):
        """
        Retrieve details of a contact by their contact ID.
        
        :param contact_id: The HubSpot contact ID.
        :return: Contact details if found, else None.
        """
        try:
            response = self.client.crm.contacts.basic_api.get_by_id(contact_id)
            return response
        except ContactsUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to get contact: {e.body}") from e
        except ContactsApiException as e:
            raise ConfigError(f"Hubspot: Error getting contact: {e.body}") from e

    def create_contact(self, properties: dict):
        """
        Create a new contact in HubSpot.
        
        :param properties: A dictionary with contact properties (e.g., firstname, lastname, email, etc.).
        :return: The created contact object.
        """
        contact_input = SimplePublicObjectInput(properties=properties)
        try:
            response = self.client.crm.contacts.basic_api.create(simple_public_object_input=contact_input)
            return response
        except ContactsUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to create contact: {e.body}") from e
        except ContactsApiException as e:
            raise ConfigError(f"Hubspot: Error creating contact: {e.body}") from e

    def update_contact(self, contact_id: str, properties: dict):
        """
        Update an existing contact in HubSpot.
        
        :param contact_id: The HubSpot contact ID.
        :param properties: A dictionary with updated contact properties.
        :return: The updated contact object.
        """
        contact_input = SimplePublicObjectInput(properties=properties)
        try:
            response = self.client.crm.contacts.basic_api.update(contact_id, simple_public_object_input=contact_input)
            return response
        except ContactsUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to update contact: {e.body}") from e
        except ContactsApiException as e:
            raise ConfigError(f"Hubspot: Error updating contact: {e.body}") from e

    def delete_contact(self, contact_id: str):
        """
        Delete a contact by their contact ID.
        
        :param contact_id: The HubSpot contact ID.
        :return: True if the contact was deleted, False otherwise.
        """
        try:
            self.client.crm.contacts.basic_api.archive(contact_id)
            return True
        except ContactsUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to delete contact: {e.body}") from e
        except ContactsApiException as e:
            raise ConfigError(f"Hubspot: Error deleting contact: {e.body}") from e

    def restore_deleted_contact(self, contact_id: str):
        """
        Restore a previously deleted contact in HubSpot.

        :param contact_id: The HubSpot contact ID.
        :return: The restored contact object if successful, None otherwise.
        """
        try:
            response = self.client.crm.contacts.gdpr_api.restore(contact_id)
            return response.to_dict()
        except ContactsUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to restore deleted contact: {e.body}") from e
        except ContactsApiException as e:
            raise ConfigError(f"Hubspot: Error restoring deleted contact: {e.body}") from e

    def search_contacts(self, query: str):
        """
        Search for contacts in HubSpot by a specific query.

        :param query: The search term to look for in contact properties.
        :return: List of contacts matching the search criteria.
        """
        try:
            search_filter = {"filters": [{"propertyName": "email", "operator": "EQ", "value": query}]}
            search_request = {"filterGroups": [search_filter], "limit": 10}
            response = self.client.crm.contacts.search_api.do_search(search_request)
            return [contact.to_dict() for contact in response.results]
        except ContactsUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to search contacts: {e.body}") from e
        except ContactsApiException as e:
            raise ConfigError(f"Hubspot: Error searching contacts: {e.body}") from e

    def batch_create_contacts(self, contacts: list):
        """
        Create multiple contacts in HubSpot in a batch.

        :param contacts: List of dictionaries, each containing contact properties.
        :return: List of created contact objects.
        """
        try:
            inputs = [SimplePublicObjectInput(properties=contact) for contact in contacts]
            response = self.client.crm.contacts.batch_api.create(inputs)
            return [contact.to_dict() for contact in response.results]
        except ContactsUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to batch create contacts: {e.body}") from e
        except ContactsApiException as e:
            raise ConfigError(f"Hubspot: Error batch creating contacts: {e.body}") from e

    def batch_update_contacts(self, updates: list):
        """
        Update multiple contacts in HubSpot in a batch.

        :param updates: List of dictionaries, each containing a contact ID and properties to update.
        :return: List of updated contact objects.
        """
        try:
            inputs = [
                {"id": update["id"], "properties": update["properties"]}
                for update in updates
            ]
            response = self.client.crm.contacts.batch_api.update(inputs)
            return [contact.to_dict() for contact in response.results]
        except ContactsUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to batch update contacts: {e.body}") from e
        except ContactsApiException as e:
            raise ConfigError(f"Hubspot: Error batch updating contacts: {e.body}") from e

    def associate_contact_with_company(self, contact_id: str, company_id: str):
        """
        Associate a contact with a company in HubSpot.

        :param contact_id: The HubSpot contact ID.
        :param company_id: The HubSpot company ID.
        :return: True if association was successful, False otherwise.
        """
        try:
            self.client.crm.contacts.associations_api.create(
                contact_id, 'company', company_id, 'contact_to_company'
            )
            return True
        except ContactsUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to associate contact with company: {e.body}") from e
        except ContactsApiException as e:
            raise ConfigError(f"Hubspot: Error associating contact with company: {e.body}") from e

    def check_contact_exists(self, email: str) -> bool:
        """
        Check if a contact exists in HubSpot based on their email address.

        :param email: The email address of the contact.
        :return: True if contact exists, False otherwise.
        """
        try:
            search_filter = {"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}
            search_request = {"filterGroups": [search_filter], "limit": 1}
            response = self.client.crm.contacts.search_api.do_search(search_request)
            return len(response.results) > 0
        except ContactsUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to check contact existence: {e.body}") from e
        except ContactsApiException as e:
            raise ConfigError(f"Hubspot: Error checking contact existence: {e.body}") from e

    def get_contact_properties(self):
        """
        List all contact properties available in HubSpot.
        
        :return: A list of contact properties.
        """
        try:
            response = self.client.crm.properties.core_api.get_all(object_type="contacts")
            prop_list = [property.name for property in response.results]
            properties = [
                {
                    "name": property.name,
                    "label": property.label,
                    "description": property.description,
                    "type": property.type,
                    "archived": property.archived
                }
                for property in response.results
            ]
            return {'list': prop_list, 'properties' : properties}
        except PropertiesUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to list contact properties: {e.body}") from e
        except PropertiesApiException as e:
            raise ConfigError(f"Hubspot: Error listing contact properties: {e.body}") from e
    
    def get_contact_lifecyclestage(self):
        """
        List all contact lifecyclestages available in HubSpot.
        
        :return: A list of contact lifecyclestages.
        """
        try:
            lifecyclestage_property = self.client.crm.properties.core_api.get_by_name('contacts', 'lifecyclestage')
            lifecyclestage_list = [option.value for option in lifecyclestage_property.options]
            lifecyclestage_options = [
                {"value": option.value, "label": option.label} for option in lifecyclestage_property.options
            ]
            return {'list': lifecyclestage_list, 'properties': lifecyclestage_options}
        except PropertiesUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to list contact lifecyclestage: {e.body}") from e
        except PropertiesApiException as e:
            raise ConfigError(f"Hubspot: Error listing contact lifecyclestage: {e.body}") from e

    def get_contact_associations(self, contact_id: str, to_object_type: str = 'company'):
        """
        Retrieve associations of a contact with other objects (default: companies).

        :param contact_id: The HubSpot contact ID.
        :param to_object_type: The type of associated objects (default is 'company').
        :return: List of associated object IDs.
        """
        try:
            response = self.client.crm.contacts.associations_api.get_all(contact_id, to_object_type)
            return [assoc.id for assoc in response.results]
        except ContactsUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to get contact associations: {e.body}") from e
        except ContactsApiException as e:
            raise ConfigError(f"Hubspot: Error getting contact associations: {e.body}") from e
