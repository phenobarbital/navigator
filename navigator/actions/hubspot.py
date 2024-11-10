from hubspot import HubSpot as HubSpot
from hubspot.crm.contacts import SimplePublicObjectInput as ContactSimplePublicObjectInput
from hubspot.crm.companies import SimplePublicObjectInput as CompanySimplePublicObjectInput
from hubspot.crm.objects.leads import SimplePublicObjectInputForCreate as LeadSimplePublicObjectInputForCreate
from hubspot.crm.objects.leads.exceptions import ApiException as LeadsApiException, UnauthorizedException as LeadsUnauthorizedException
from hubspot.crm.contacts.exceptions import ApiException as ContactsApiException, UnauthorizedException as ContactsUnauthorizedException
from hubspot.crm.companies.exceptions import ApiException as CompaniesApiException, UnauthorizedException as CompaniesUnauthorizedException
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

    async def run(self):
        pass

    async def open(self):
        pass

    async def close(self):
        pass


    async def get_contacts(self):
        """
        Retrieve details of a all contacts
        
        :return: List of Contacts details if found, else None.
        """
        try:
            after = None
            all_contacts = []
            client = HubSpot(access_token=self.token)
            while True:
                response = client.crm.contacts.basic_api.get_page(limit=100, after=after)
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

    async def search_contacts(self, property: str, value: str):
        """
        Search for contacts in HubSpot by a specific query.

        :param query: The search term to look for in contact properties.
        :return: List of contacts matching the search criteria.
        """
        try:
            client = HubSpot(access_token=self.token)
            search_filter = {"filters": [{"propertyName": property, "operator": "EQ", "value": value}]}
            search_request = {"filterGroups": [search_filter], "limit": 10}
            response = client.crm.contacts.search_api.do_search(search_request)
            return [contact.to_dict() for contact in response.results]
        except ContactsUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to search contacts: {e.body}") from e
        except ContactsApiException as e:
            raise ConfigError(f"Hubspot: Error searching contacts: {e.body}") from e

    async def create_contact(self, properties: dict):
        """
        Create a new contact in HubSpot.
        
        :param properties: A dictionary with contact properties.
        :return: The created contact object.
        """
        contact_input = ContactSimplePublicObjectInput(properties=properties)
        try:
            client = HubSpot(access_token=self.token)
            response = client.crm.contacts.basic_api.create(simple_public_object_input_for_create=contact_input)
            return response.to_dict()
        except ContactsUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to create contact: {e.body}") from e
        except ContactsApiException as e:
            raise ConfigError(f"Hubspot: Error creating contact: {e.body}") from e

    async def get_contact_properties(self):
        """
        List all contact properties available in HubSpot.
        
        :return: A list of contact properties.
        """
        try:
            client = HubSpot(access_token=self.token)
            response = client.crm.properties.core_api.get_all(object_type="contacts")
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
    
    async def get_contact_lifecyclestage(self):
        """
        List all contact lifecyclestages available in HubSpot.
        
        :return: A list of contact lifecyclestages.
        """
        try:
            client = HubSpot(access_token=self.token)
            lifecyclestage_property = client.crm.properties.core_api.get_by_name('contacts', 'lifecyclestage')
            lifecyclestage_list = [option.value for option in lifecyclestage_property.options]
            lifecyclestage_options = [
                {"value": option.value, "label": option.label} for option in lifecyclestage_property.options
            ]
            return {'list': lifecyclestage_list, 'properties': lifecyclestage_options}
        except PropertiesUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to list contact lifecyclestage: {e.body}") from e
        except PropertiesApiException as e:
            raise ConfigError(f"Hubspot: Error listing contact lifecyclestage: {e.body}") from e

    async def get_companies(self):
        """
        Retrieve details of all companies.

        :return: List of Company details if found, else None.
        """
        try:
            after = None
            all_companies = []
            while True:
                client = HubSpot(access_token=self.token)
                response = client.crm.companies.basic_api.get_page(limit=100, after=after)
                for company in response.results:
                    all_companies.append(company.to_dict())
                if not response.paging or not response.paging.next:
                    break
                after = response.paging.next.after
            return all_companies
        except CompaniesUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to get companies: {e.body}") from e
        except CompaniesApiException as e:
            raise ConfigError(f"Hubspot: Error getting companies: {e.body}") from e

    async def search_companies(self, property: str, value: str):
        """
        Search for companies in HubSpot by a specific query.

        :param query: The search term to look for in company properties (e.g., domain).
        :return: List of companies matching the search criteria.
        """
        try:
            client = HubSpot(access_token=self.token)
            search_filter = {"filters": [{"propertyName": property, "operator": "EQ", "value": value}]}
            search_request = {"filterGroups": [search_filter], "limit": 10}
            response = client.crm.companies.search_api.do_search(search_request)
            return [company.to_dict() for company in response.results]
        except CompaniesUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to search companies: {e.body}") from e
        except CompaniesApiException as e:
            raise ConfigError(f"Hubspot: Error searching companies: {e.body}") from e

    async def create_company(self, properties: dict):
        """
        Create a new company in HubSpot.

        :param properties: A dictionary with company properties.
        :return: The created company object.
        """
        company_input = CompanySimplePublicObjectInput(properties=properties)
        try:
            client = HubSpot(access_token=self.token)
            response = client.crm.companies.basic_api.create(simple_public_object_input_for_create=company_input)
            return response.to_dict()
        except CompaniesUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to create company: {e.body}") from e
        except CompaniesApiException as e:
            raise ConfigError(f"Hubspot: Error creating company: {e.body}") from e

    async def get_company_properties(self):
        """
        List all company properties available in HubSpot.
        
        :return: A list of company properties.
        """
        try:
            client = HubSpot(access_token=self.token)
            response = client.crm.properties.core_api.get_all(object_type="companies")
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
            raise FailedAuth(f"Hubspot: Unauthorized to list company properties: {e.body}") from e
        except PropertiesApiException as e:
            raise ConfigError(f"Hubspot: Error listing company properties: {e.body}") from e

    async def get_leads(self, limit: int = 100):
        """
        Retrieve a list of leads in HubSpot.

        :param limit: The maximum number of leads to retrieve.
        :return: List of lead details.
        """
        try:
            after = None
            all_leads = []
            while True:
                client = HubSpot(access_token=self.token)
                response = client.crm.objects.leads.basic_api.get_page(limit=limit, after=after)
                for lead in response.results:
                    all_leads.append(lead.to_dict())
                if not response.paging or not response.paging.next:
                    break
                after = response.paging.next.after
            return all_leads
        except LeadsUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to get leads: {e.body}") from e
        except LeadsApiException as e:
            raise ConfigError(f"Hubspot: Error getting leads: {e.body}") from e

    async def search_leads(self, property: str, value: str):
        """
        Search for leads in HubSpot by a specific property and value.

        :param property: The property name to search for.
        :param value: The value of the property to match.
        :return: List of leads matching the search criteria.
        """
        try:
            client = HubSpot(access_token=self.token)
            search_filter = {"filters": [{"propertyName": property, "operator": "EQ", "value": value}]}
            search_request = {"filterGroups": [search_filter], "limit": 10}
            response = client.crm.objects.leads.search_api.do_search(search_request)
            return [lead.to_dict() for lead in response.results]
        except LeadsUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to search leads: {e.body}") from e
        except LeadsApiException as e:
            raise ConfigError(f"Hubspot: Error searching leads: {e.body}") from e

    async def create_lead(self, properties: dict, associations: list):
        """
        Create a new lead in HubSpot.

        :param properties: A dictionary with lead properties.
        :return: The created lead object.
        """
        lead_input = LeadSimplePublicObjectInputForCreate(properties=properties, associations=associations)
        try:
            client = HubSpot(access_token=self.token)
            response = client.crm.objects.leads.basic_api.create(simple_public_object_input_for_create=lead_input)
            return response.to_dict()
        except LeadsUnauthorizedException as e:
            raise FailedAuth(f"Hubspot: Unauthorized to create lead: {e.body}") from e
        except LeadsApiException as e:
            raise ConfigError(f"Hubspot: Error creating lead: {e.body}") from e

    async def get_lead_properties(self):
        """
        List all lead properties available in HubSpot.
        
        :return: A list of lead properties.
        """
        try:
            client = HubSpot(access_token=self.token)
            response = client.crm.properties.core_api.get_all(object_type="leads")
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
            raise FailedAuth(f"Hubspot: Unauthorized to list lead properties: {e.body}") from e
        except PropertiesApiException as e:
            raise ConfigError(f"Hubspot: Error listing lead properties: {e.body}") from e
