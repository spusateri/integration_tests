import fauxfactory
import pytest
import yaml

from cfme import test_requirements
from cfme.fixtures.automate import DatastoreImport
from cfme.infrastructure.provider.rhevm import RHEVMProvider
from cfme.markers.env_markers.provider import ONE
from cfme.services.service_catalogs import ServiceCatalogs
from cfme.utils.appliance import ViaSSUI
from cfme.utils.appliance.implementations.ssui import navigate_to as ssui_nav
from cfme.utils.appliance.implementations.ui import navigate_to
from cfme.utils.conf import cfme_data
from cfme.utils.ftp import FTPClientWrapper
from cfme.utils.log_validator import LogValidator
from cfme.utils.wait import wait_for


pytestmark = [
    test_requirements.dialog,
    pytest.mark.tier(2)
]

WIDGETS = {
    "Text Box": ("input", fauxfactory.gen_alpha()),
    "Check Box": ("checkbox", True),
    "Text Area": ("input", fauxfactory.gen_alpha()),
    "Radio Button": ("radiogroup", None),
    "Dropdown": ("dropdown", "One"),
    "Tag Control": ("dropdown", "Production Linux Team"),
    "Timepicker": ("input", "")
}


@pytest.fixture(scope="function")
def service_dialog(appliance, widget_name):
    service_dialog = appliance.collections.service_dialogs
    element_data = {
        'element_information': {
            'ele_label': fauxfactory.gen_alphanumeric(start="label_"),
            'ele_name': fauxfactory.gen_alphanumeric(start="name_"),
            'ele_desc': fauxfactory.gen_alphanumeric(start="desc_"),
            'choose_type': widget_name
        },
        'options': {
            'field_required': True,
        }
    }
    if widget_name == "Tag Control":
        # Need to select category to create service dialog of tag control widget
        element_data['options']['field_category'] = "Owner"
    sd = service_dialog.create(label=fauxfactory.gen_alphanumeric(start="dialog_"),
                               description="my dialog")
    tab = sd.tabs.create(tab_label=fauxfactory.gen_alphanumeric(start='tab_'),
                         tab_desc="my tab desc")
    box = tab.boxes.create(box_label=fauxfactory.gen_alphanumeric(start='box_'),
                           box_desc="my box desc")
    box.elements.create(element_data=[element_data])
    yield sd, element_data
    sd.delete_if_exists()


@pytest.fixture(scope="function")
def catalog_item_local(appliance, service_dialog, catalog):
    sd, element_data = service_dialog
    item_name = fauxfactory.gen_alphanumeric(15, start="cat_item_")
    catalog_item = appliance.collections.catalog_items.create(
        appliance.collections.catalog_items.GENERIC,
        name=item_name,
        description="my catalog",
        display_in=True,
        catalog=catalog,
        dialog=sd)
    yield catalog_item
    catalog_item.delete_if_exists()


@pytest.mark.tier(1)
@pytest.mark.parametrize(
    "widget_name", list(WIDGETS.keys()),
    ids=["_".join(w.split()).lower() for w in WIDGETS.keys()],
)
def test_required_dialog_elements(appliance, catalog_item_local, service_dialog, widget_name):
    """
    Polarion:
        assignee: nansari
        casecomponent: Services
        initialEstimate: 1/4h
        caseimportance: high
        startsin: 5.10
        testSteps:
            1. Create a dialog. Set required true to element
            2. Use the dialog in a catalog.
            3. Order catalog.
         expectedResults:
            1.
            2.
            3. Submit button should be disabled
    """
    sd, element_data = service_dialog
    service_catalogs = ServiceCatalogs(
        appliance, catalog_item_local.catalog, catalog_item_local.name
    )
    view = navigate_to(service_catalogs, "Order")
    ele_name = element_data["element_information"]["ele_name"]
    choose_type = element_data["element_information"]["choose_type"]
    wt, value = WIDGETS[widget_name]

    if choose_type not in ["Radio Button", "Timepicker"]:
        assert view.submit_button.disabled
        getattr(view.fields(ele_name), wt).fill(value)
        wait_for(lambda: not view.submit_button.disabled, delay=0.2, timeout=15)
    elif choose_type == "Timepicker":
        # Time is already selected in this widget. So checking submit button is getting disabled
        # after removing value from that field.
        assert not view.submit_button.disabled
        getattr(view.fields(ele_name), wt).fill(value)
        assert view.submit_button.disabled
    else:
        # In case of Radio Button, one option is always selected. So submit button is not disabled.
        assert not view.submit_button.disabled


@pytest.mark.meta(automates=[1692736])
@pytest.mark.customer_scenario
@pytest.mark.tier(1)
@pytest.mark.parametrize("file_name", ["bz_1692736.yml"], ids=["dialog"])
def test_validate_not_required_dialog_element(appliance, file_name,
                                              generic_catalog_item_with_imported_dialog):
    """
    Polarion:
        assignee: nansari
        casecomponent: Services
        initialEstimate: 1/4h
        caseimportance: high
        startsin: 5.10
        testSteps:
            1. Create a dialog with a field which needs to 'Validate' but is not 'Required'
            2. Execute the dialog as a Catalog Service
            3. Try submitting the dialog only with the 'Required' Fields
        expectedResults:
            1.
            2.
            3. It should be able to submit the form with only 'Required' fields

    Bugzilla:
        1692736
    """
    catalog_item, sd, _ = generic_catalog_item_with_imported_dialog

    service_catalog = ServiceCatalogs(appliance, catalog_item.catalog, catalog_item.name)
    view = navigate_to(service_catalog, "Order")

    # inputs on page
    required = view.fields("required").input
    validated = view.fields("validate").input

    def clean_inputs():
        required.fill("")
        validated.fill("")

    # Check required
    clean_inputs()
    assert required.warning == "This field is required"
    assert view.submit_button.disabled
    required.fill(fauxfactory.gen_alphanumeric())
    assert wait_for(lambda: not required.warning, timeout=15)
    assert not view.submit_button.disabled

    # Check validate
    clean_inputs()
    required.fill(fauxfactory.gen_alphanumeric())
    validated.fill(fauxfactory.gen_alpha())
    msg = (
        "Entered text should match the format: "
        "^(?:[1-9]|(?:[1-9][0-9])|(?:[1-9][0-9][0-9])|(?:900))$"
    )
    assert validated.warning == msg
    assert view.submit_button.disabled
    validated.fill("123")  # matching pattern
    assert wait_for(lambda: not validated.warning, timeout=15)
    assert not view.submit_button.disabled


@pytest.mark.meta(coverage=[1696474])
@pytest.mark.manual
@pytest.mark.tier(2)
def test_dynamic_dialog_fields_ansible_tower_templates():
    """

    Bugzilla:
        1696474

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/2h
        testSteps:
            1. Add dynamic dialog with "text area" field
            2. Add service catalog with above created dialog
            3. Navigate to order page of service
            4. Order the service
        expectedResults:
            1.
            2.
            3.
            4. Populated "text area" fields should pass correct value to ansible tower templates
    """
    pass


@pytest.mark.meta(automates=[1707961])
@pytest.mark.tier(2)
@pytest.mark.ignore_stream("5.10")
def test_dialog_editor_modify_field(dialog):
    """
    Bugzilla:
        1707961

    Polarion:
        assignee: nansari
        startsin: 5.11
        casecomponent: Services
        initialEstimate: 1/16h
        testSteps:
            1. Add dialog
            2. Edit a dialog
            3. Edit and save as many fields as many times as you like
            4. Exit without saving the dialog
        expectedResults:
            1.
            2.
            3.
            4. The UI should confirm that you want to exit without saving your dialog
    """
    # As dialog created with rest sometime force nav required.
    view = navigate_to(dialog, "Edit", force=True)
    view.description.fill(fauxfactory.gen_alpha())
    view.cancel_button.click(handle_alert=True)
    view = navigate_to(dialog, "Edit")
    assert view.description.read() == dialog.description
    view.cancel_button.click(handle_alert=False)


@pytest.mark.meta(coverage=[1706848])
@pytest.mark.manual
@pytest.mark.tier(2)
def test_specific_dates_and_time_in_timepicker():
    """

    Bugzilla:
        1706848

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/16h
        testSteps:
            1. Create a dialog with timepicker
            2. Select specific dates and time, Save
            3. Edit the dialog
        expectedResults:
            1.
            2.
            3. Able to set specific dates and time in timepicker
    """
    pass


@pytest.mark.customer_scenario
@pytest.mark.meta(automates=[1706693])
@pytest.mark.tier(2)
@pytest.mark.parametrize("import_data", [DatastoreImport("bz_1706693.zip", "bz_1706693", None)],
                         ids=["datastore"])
@pytest.mark.parametrize("file_name", ["bz_1706693.yaml"], ids=["refresh_dialog"])
def test_dynamic_field_on_refresh_button(appliance, import_datastore, import_data, file_name,
                                         generic_catalog_item_with_imported_dialog):
    """
    Bugzilla:
        1706693

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/16h
        testSteps:
            1. Import Datastore and dialog
            2. Add service catalog with above created dialog
            3. Navigate to order page of service
            4. In service Order page
        expectedResults:
            1.
            2.
            3.
            4. dynamic field shouldn't be blank
    """
    catalog_item, sd, ele_label = generic_catalog_item_with_imported_dialog

    # These are the labels(keys) and names(values) of widgets appeared while ordering catalog item.
    # We can not access these values from imported dialog. Hence created dict of these static values
    label_element_map = {'var_1 - copied': 'var_2', 'var_2 - copied': 'var_3',
                         'merged': 'var_2_var_3'}

    service_catalogs = ServiceCatalogs(appliance, catalog_item.catalog, catalog_item.name)
    view = navigate_to(service_catalogs, "Order")
    for label, ele_name in label_element_map.items():
        before_refresh = view.fields(ele_name).input.read()
        view.fields(ele_name).input.fill(fauxfactory.gen_alphanumeric())
        view.fields(label).refresh.click()
        assert view.fields(ele_name).input.read() == before_refresh


@pytest.mark.meta(automates=[1702343])
@pytest.mark.tier(2)
def test_clicking_created_catalog_item_in_the_list(appliance, generic_catalog_item):
    """
    Bugzilla:
        1702343

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/6h
        testSteps:
            1. Go to Services > Catalogs > Catalog Items accordion
            2. Configuration > Add a New Catalog Item, choose some Catalog Item type
            3. Fill in the required info and click on Add button
            4. After successfully saving the Catalog Item, click on the same Catalog Item in list
        expectedResults:
            1.
            2.
            3.
            4. Catalog Item's summary screen should appear
    """
    with LogValidator("/var/www/miq/vmdb/log/evm.log", failure_patterns=[".*ERROR.*"]).waiting(
            timeout=120):
        view = navigate_to(appliance.collections.catalog_items, "All")
        for cat_item in view.table:
            if cat_item[2].text == generic_catalog_item.name:
                cat_item[2].click()
                break
        assert view.title.text == f'Service Catalog Item "{generic_catalog_item.name}"'


@pytest.mark.meta(coverage=[1698439])
@pytest.mark.manual
@pytest.mark.tier(2)
def test_dialog_based_on_aws_orchestration_template():
    """

    Bugzilla:
        1698439

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/6h
        testSteps:
            1. create an aws template with an optional value "timeout"
            2. create a dialog that will offer an option to overwrite "timeout"
            with a custom value typed at input
            3. Navigate to order page of service
            4. provision using a non-zero value in timeout
        expectedResults:
            1.
            2.
            3.
            4. the value input should be passed
    """
    pass


@pytest.mark.meta(automates=[1686076])
@pytest.mark.tier(2)
@pytest.mark.ignore_stream("5.10")
@pytest.mark.provider([RHEVMProvider], selector=ONE)
def test_provider_field_should_display_in_vm_details_page_in_ssui(appliance, provider,
                                                                  setup_provider,
                                                                  service_vm):
    """

    Bugzilla:
        1686076

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/6h
        testSteps:
            1. Create a catalog item of vmware or RHEV.
            2. Navigate to order page of service
            3. Order Service
            4. Go to Service UI. Click on VM
        expectedResults:
            1.
            2.
            3.
            4. Vm details page should display which provider it belongs to
    """
    service, vm = service_vm

    with appliance.context.use(ViaSSUI):
        view = ssui_nav(service, "VMDetails")
        assert provider.name in view.provider_info.read()
        assert vm.name in view.vm_info.read()


@pytest.mark.meta(coverage=[1685266])
@pytest.mark.manual
@pytest.mark.tier(2)
def test_service_dialog_date_datetime_picker_dynamic_dialog():
    """

    Bugzilla:
        1685266

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/6h
        testSteps:
            1. Import Datastore
            2. Create a dialog with a Date Picker/DateTmie picker
            3. Make the dialog field dynamic
            4. Create a service and add your dialog
            5. Navigate to order page of service
            6. In service Order page
        expectedResults:
            1.
            2.
            3.
            4.
            5.
            6. Date should be today
    """
    pass


@pytest.mark.customer_scenario
@pytest.mark.meta(automates=[1684567])
@pytest.mark.tier(2)
@pytest.mark.ignore_stream("5.10")
@pytest.mark.parametrize("import_data", [DatastoreImport("bz_1684567.zip", "bz_1684567", None)],
                         ids=["datastore"])
@pytest.mark.parametrize("file_name", ["bz_1684567.yml"], ids=["load-init"])
def test_service_dd_dialog_load_values_on_init(appliance, import_datastore, import_data, file_name,
                                               generic_catalog_item_with_imported_dialog):
    """
    Bugzilla:
        1684567

    Polarion:
        assignee: nansari
        startsin: 5.11
        casecomponent: Services
        initialEstimate: 1/6h
        testSteps:
            1. Import the attached yaml dialog export and automate domains.
            2. Add the dialog to a service or custom button.
            3. Navigate to order page of service
            4. In service Order page
        expectedResults:
            1.
            2.
            3.
            4. The dialog elements should not be populated as the method
              should not have run as "load_values_on_init: false" is set in the element definition.
    """
    catalog_item, sd, ele_label = generic_catalog_item_with_imported_dialog
    service_catalogs = ServiceCatalogs(appliance, catalog_item.catalog, catalog_item.name)
    view = navigate_to(service_catalogs, "Order")
    # Dynamic textbox field should be empty
    assert not view.fields("text_box").read()


@pytest.mark.meta(coverage=[1684092])
@pytest.mark.manual
@pytest.mark.tier(2)
def test_retire_catalog_bundle_service_orchestration_item():
    """

    Bugzilla:
        1684092

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/6h
        testSteps:
            1. Add ec2 provider
            2. Provisioned the catalog bundle with ServiceOrchestration item
            3. Navigate to My service page
            4. Retired the bundle
        expectedResults:
            1.
            2.
            3.
            4. Catalog bundle should retire with no error

    """
    pass


@pytest.mark.meta(coverage=[1656351])
@pytest.mark.manual
@pytest.mark.tier(2)
def test_service_catalog_orchestration_global_region():
    """

    Bugzilla:
        1656351

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/6h
        testSteps:
            1. Create a service catalog with type orchestration template (heat or Aws)
            2. Navigate to order page of service
            3. Order the above service from global region
        expectedResults:
            1.
            2.
            3. From global region, the ordering of catalog should be successful

    """
    pass


@pytest.mark.meta(coverage=[1713100])
@pytest.mark.manual
@pytest.mark.tier(2)
def test_copy_save_service_dialog_with_the_same_name():
    """

    Bugzilla:
        1713100

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/6h
        testSteps:
            1. Copy service dialog "Test Dialog" save as "Copy of Test Dialog"
            2. Copy service dialog "Test Dialog" attempt to save as "Copy of Test Dialog"
        expectedResults:
            1.
            2. Tabs shouldn't be copied and shouldn't show multiple times.

    """
    pass


@pytest.mark.meta(automates=[1696697])
@pytest.mark.customer_scenario
@pytest.mark.parametrize("file_name", ["bz_1696697.yml"], ids=["sample_dialog"],)
def test_request_details_page_tagcontrol_field(request, appliance, import_dialog,
                                               generic_catalog_item_with_imported_dialog):
    """
    Bugzilla:
        1696697

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/6h
        testSteps:
            1. Add service dialog with tagcontrol field
            2. Add catalog item with above dialog
            3. Navigate to order page of service
            4. Order the service
            5. Go to service request details page
        expectedResults:
            1.
            2.
            3.
            4.
            5. No error when go to on service request details page

    """
    catalog_item, sd, ele_label = generic_catalog_item_with_imported_dialog

    service_catalogs = ServiceCatalogs(appliance, catalog_item.catalog, catalog_item.name)
    view = navigate_to(service_catalogs, "Order")

    view.fields(ele_label).dropdown.fill("One")
    view.submit_button.click()
    request_description = 'Provisioning Service [{name}] from [{name}]'.format(
        name=catalog_item.name)
    service_request = appliance.collections.requests.instantiate(
        description=request_description,
        partial_check=True)
    request.addfinalizer(lambda: service_request.remove_request(method="rest"))
    details_view = navigate_to(service_request, "Details")
    # Request Details should appear without ui exception
    assert details_view.is_displayed


@pytest.mark.meta(coverage=[1694737])
@pytest.mark.manual
@pytest.mark.tier(2)
def test_regex_validation_should_work():
    """

    Bugzilla:
        1694737

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/6h
        testSteps:
            1. Import DataStore and Dynamic Dialog
            2. Add catalog item with above dialog
            3. Navigate to order page of service
            4. In service Order page
            5. Add values
        expectedResults:
            1.
            2.
            3.
            4.
            5. Regex validation should work
    """
    pass


@pytest.mark.tier(2)
@pytest.mark.meta(automates=[1696474])
@pytest.mark.customer_scenario
@pytest.mark.parametrize("import_data", [DatastoreImport("bz_1696474.zip", "bz_1696474", None)],
                         ids=["datastore"])
@pytest.mark.parametrize("file_name", ["bz_1696474.yml"], ids=["sample_dialog"],)
def test_dynamic_dialogs(appliance, import_datastore, generic_catalog_item_with_imported_dialog):
    """

    Bugzilla:
        1696474

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/6h
        testSteps:
            1. Import DataStore and Dynamic Dialog
            2. Add catalog item with above dialog
            3. Navigate to order page of service
            4. In service Order page
        expectedResults:
            1.
            2.
            3.
            4. All dynamic dialog functionality should work
    """
    catalog_item, _, ele_label = generic_catalog_item_with_imported_dialog

    service_catalogs = ServiceCatalogs(appliance, catalog_item.catalog, catalog_item.name)
    view = navigate_to(service_catalogs, "Order")

    data_value = fauxfactory.gen_alphanumeric()
    view.fields(ele_label).fill(data_value)

    #  'limit', 'param_vm_name', 'param_database' and 'dialog_hostname_master_appliance'
    #  Fields are coming from imported dialog.
    wait_for(
        lambda: view.fields("limit").read() == data_value and
        view.fields("param_vm_name").read() == data_value, timeout=7
    )

    # TextBox should read the appliance IP address
    view.fields("dialog_hostname_master_appliance").read() == appliance.hostname

    # Checkbox must be checked for database field
    assert view.fields("param_database").checkbox.read()


@pytest.mark.meta(coverage=[1706600])
@pytest.mark.manual
@pytest.mark.tier(2)
def test_dynamic_dialogs_on_service_request():
    """

    Bugzilla:
        1706600

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/6h
        testSteps:
            1. Import DataStore and Dynamic Dialog
            2. Add catalog item with above dialog
            3. Navigate to order page of service
            3. Order the service
            4. Click refresh until Service finishes. (Services/Requests)
            5. Double Click on your request
            6. Page down and Under 'Dialog Options' Notice the 'Text Area' field
        expectedResults:
            1.
            2.
            3.
            4.
            5.
            6. Dialog Fields should populate in the System Request
    """
    pass


@pytest.mark.meta(coverage=[1693264])
@pytest.mark.manual
@pytest.mark.tier(2)
def test_access_child_services_from_the_my_service():
    """

    Bugzilla:
        1693264

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/16h
        testSteps:
            1. create a catalog item
            2. attache the child service to above service
            3. Navigate to My Service
            4. Go to service details page
        expectedResults:
            1.
            2.
            3.
            4. Access the child service from parent section
    """
    pass


@pytest.mark.meta(coverage=[1684575])
@pytest.mark.manual
@pytest.mark.tier(2)
def test_load_values_on_init_option_service_dialog_element():
    """

    Bugzilla:
        1684575

    Polarion:
        assignee: nansari
        startsin: 5.11
        casecomponent: Services
        initialEstimate: 1/16h
        testSteps:
            1. create a service dialog
            2. In service dialog element option page
        expectedResults:
            1.
            2. Load_values_on_init button should always be enabled
    """
    pass


@pytest.mark.meta(coverage=[1677724])
@pytest.mark.manual
@pytest.mark.tier(2)
def test_datepicker_field_set_to_required():
    """

    Bugzilla:
        1677724

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/6h
        testSteps:
            1. Create dialog and add a Datepicker field to it. Set required
            2. Add the service dialog to Services
            3. Navigate to order page of service
            4. In service Order page
            5. Empty the datepicker field
            6. Order the service
        expectedResults:
            1.
            2.
            3.
            4.
            5
            6. It should show the required message
    """
    pass


@pytest.mark.meta(coverage=[1654165])
@pytest.mark.manual
@pytest.mark.tier(2)
def test_service_bundle_vms():
    """

    Bugzilla:
        1654165

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/6h
        testSteps:
            1. Create Bundle, containing 2 service items, each of which will provision a single VM
            2. Navigate to order page of service
            3. Order the Service bundle.
        expectedResults:
            1.
            2. View the Service. Both VMs should displayed, instead of the 1 VM.
    """
    pass


@pytest.mark.meta(coverage=[1660637])
@pytest.mark.manual
@pytest.mark.tier(2)
def test_service_service_vms_retires_archived():
    """

    Bugzilla:
        1660637

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/6h
        testSteps:
            1. Create service which will provision a VM
            2. Navigate to order page of service
            3. Order the Service bundle.
            4. Navigate to My service page
            5. Retire the service
        expectedResults:
            1.
            2.
            3.
            4.
            5. Service should retire the VMs as well and Vm should archive
    """
    pass


@pytest.mark.meta(automates=[1558926])
@pytest.mark.tier(2)
@pytest.mark.parametrize(
    "import_data",
    [DatastoreImport("bz_1558926.zip", "bz_1558926", None)],
    ids=["domain"],
)
@pytest.mark.parametrize("file_name", ["bz_1558926.yml"], ids=["dialog"])
@pytest.mark.parametrize('create_vm', ['full_template'], indirect=True)
@pytest.mark.provider([RHEVMProvider], scope='function', selector=ONE)
def test_service_dialog_expression_method(appliance, setup_provider, create_vm,
                                          import_datastore, import_data, file_name,
                                          generic_catalog_item_with_imported_dialog):
    """
    Bugzilla:
        1558926

    Polarion:
        assignee: nansari
        startsin: 5.10
        casecomponent: Services
        initialEstimate: 1/6h
        testSteps:
            1. Import datastore and import dialog
            2. Add catalog item with above dialog
            3. Navigate to order page of service
            4. In service order page
            5. Add values in expression field
        expectedResults:
            1.
            2.
            3.
            4.
            5. Expression method should work
    """
    catalog_item, sd, ele_label = generic_catalog_item_with_imported_dialog
    service_catalogs = ServiceCatalogs(
        appliance, catalog=catalog_item.catalog, name=catalog_item.name
    )
    view = navigate_to(service_catalogs, "Order")
    assert create_vm.name in [
        opt.text for opt in view.fields("dropdown_list_1").dropdown.all_options
    ]


@pytest.mark.customer_scenario
@pytest.mark.meta(automates=[1729379, 1749650])
@pytest.mark.tier(2)
@pytest.mark.parametrize("import_data", [DatastoreImport("bz_1729379.zip", "bz_1729379", None)],
                         ids=["datastore"])
@pytest.mark.parametrize("file_name", ["bz_1729379.yml"], ids=["load-tag"])
def test_service_dynamic_dialog_tagcontrol(appliance, import_datastore, import_data,
                                           generic_catalog_item_with_imported_dialog):
    """
    Bugzilla:
        1729379
        1749650

    Polarion:
        assignee: nansari
        casecomponent: Services
        initialEstimate: 1/6h
        startsin: 5.10
        testSteps:
            1. Import datastore and import dialog
            2. Add catalog item with above dialog
            3. Navigate to order page of service
            4. In service order page
            5. Choose a value from the tag control drop down
        expectedResults:
            1.
            2.
            3.
            4.
            5. Tag control drop down should show correct values
    """
    catalog_item, sd, ele_label = generic_catalog_item_with_imported_dialog
    service_catalogs = ServiceCatalogs(appliance, catalog_item.catalog, catalog_item.name)
    view = navigate_to(service_catalogs, "Order")

    view.fields('tag_control_1').dropdown.fill("London")
    wait_for(
        lambda: view.fields("tag_control_1").read() == "London" and
        view.fields('text_box_1').read() == "Tag: 'London'", timeout=7
    )

    view.fields('tag_control_1').dropdown.fill("New York")
    wait_for(
        lambda: view.fields("tag_control_1").read() == "New York" and
        view.fields('text_box_1').read() == "Tag: 'New York'", timeout=7
    )


@pytest.mark.meta(coverage=[1744413])
@pytest.mark.manual
@pytest.mark.tier(2)
def test_datepicker_in_service_request():
    """
    Bugzilla:
        1744413

    Polarion:
        assignee: nansari
        casecomponent: Services
        initialEstimate: 1/6h
        startsin: 5.10
        testSteps:
            1. Create Dialog with Date picker
            2. Create Service with the dialog and order the service
            3. Mention a date for the date picker
            4. Navigate to Services -> Requests -> [your_service] -> Dialog Options
        expectedResults:
            1.
            2.
            3.
            4. Date picker should show correct selected dates
    """
    pass


@pytest.mark.meta(coverage=[1740823])
@pytest.mark.manual
@pytest.mark.tier(2)
def test_dialog_dropdown_integer_required():
    """
    Bugzilla:
        1740823

    Polarion:
        assignee: nansari
        casecomponent: Services
        initialEstimate: 1/16h
        startsin: 5.10
        testSteps:
            1. Create a multi select dropdown using the default "One, Two, Three" values.
            2. Add dialog to catalog item
            3. Order the new item
            4. Go to your multi select dropdown and choose the value "<None>"
            5. Select additional options, notice that displayed list of choices includes "<None>"
        expectedResults:
            1.
            2.
            3.
            4.
            5. "<None>" should not be displayed in the list of selected options
    """
    pass


@pytest.mark.tier(2)
@pytest.mark.meta(automates=[1740899])
@pytest.mark.customer_scenario
@pytest.mark.parametrize("file_name", ["bz_1740899.yml"], ids=["sample_dialog"],)
def test_dialog_dropdown_int_required(appliance, generic_catalog_item_with_imported_dialog):
    """
    Bugzilla:
        1740899
    Polarion:
        assignee: nansari
        casecomponent: Services
        initialEstimate: 1/16h
        startsin: 5.10
        testSteps:
            1. Create a dialog dropdown that is required with a value type of integer
            2. Order a catalog item that uses that dialog
            3. Make a selection for the dropdown
        expectedResults:
            1.
            2.
            3. The field should validate successfully
    """
    catalog_item, _, ele_label = generic_catalog_item_with_imported_dialog

    service_catalogs = ServiceCatalogs(appliance, catalog_item.catalog, catalog_item.name)
    view = navigate_to(service_catalogs, "Order")

    view.fields(ele_label).dropdown.fill("2")
    wait_for(lambda: not view.submit_button.disabled, timeout=7)


@pytest.mark.tier(1)
@pytest.mark.meta(automates=[1554780])
@pytest.mark.customer_scenario
@pytest.mark.parametrize("file_name", ["bz_1554780.yml"], ids=["sample_dialog"],)
def test_dialog_default_value_integer(appliance, generic_catalog_item_with_imported_dialog,
                                      file_name):
    """
    Bugzilla:
        1554780
    Polarion:
        assignee: nansari
        casecomponent: Services
        initialEstimate: 1/4h
        testtype: functional
        startsin: 5.10
    """
    catalog_item, _, ele_label = generic_catalog_item_with_imported_dialog
    service_catalogs = ServiceCatalogs(appliance, catalog_item.catalog, catalog_item.name)

    # download yaml file
    fs = FTPClientWrapper(cfme_data.ftpserver.entities.dialogs)
    file_path = fs.download(file_name)
    with open(file_path, "r") as stream:
        dialog_data = yaml.load(stream, Loader=yaml.BaseLoader)
        default_drop = dialog_data[0]["dialog_tabs"][0]["dialog_groups"][0]["dialog_fields"][0][
            "default_value"
        ]
        default_radio = dialog_data[0]["dialog_tabs"][0]["dialog_groups"][0]["dialog_fields"][1][
            "default_value"
        ]

    view = navigate_to(service_catalogs, "Order")
    assert (
        view.fields("dropdown").read() == default_drop
        and view.fields("radio").read() == default_radio
    )
